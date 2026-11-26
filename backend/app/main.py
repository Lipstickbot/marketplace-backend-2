from collections import OrderedDict
from contextlib import asynccontextmanager
import math
import time
from typing import Annotated
from pathlib import Path
from uuid import uuid4
from urllib.parse import urlsplit, parse_qs, urlencode
import re

from fastapi import APIRouter, Depends, FastAPI, Request, Response
from fastapi.routing import APIRoute
from fastapi.staticfiles import StaticFiles
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import httpx

from .auth import current_token, current_user, gateway
from .config import Settings
from .errors import APIError
from .models import ConfirmationCode, ConfirmationEmail, GoogleStartInput, GoogleExchangeInput, LoginInput, Principal, ProfilePatch, RefreshInput, SessionResponse, SignupInput, SignupResponse
from .supabase import SupabaseGateway
from .marketplace import router as marketplace_router
from .execution import router as execution_router
from .engine_client import EngineClient
from .runtime_store import RuntimeStore
from .body_limit import BodySizeLimit
from .integrations import router as integrations_router
from .payments import load_paylink_test, router as payments_router


class AuthRateLimiter:
    """Bounded, per-process limiter. Reverse proxy must limit across replicas."""
    def __init__(self, limit: int):
        self.limit = limit
        self.entries: OrderedDict[str, tuple[float, int]] = OrderedDict()

    def check(self, key: str) -> None:
        now = time.monotonic()
        while self.entries and next(iter(self.entries.values()))[0] <= now:
            self.entries.popitem(last=False)
        deadline, count = self.entries.get(key, (now + 60, 0))
        if count >= self.limit or (key not in self.entries and len(self.entries) >= 10000):
            raise APIError(429, "auth_rate_limited", "Слишком много попыток. Попробуйте позже.",
                           {"Retry-After": str(max(1, math.ceil(deadline - now)))})
        self.entries[key] = (deadline, count + 1)


def create_app(settings: Settings | None = None, *, transport: httpx.AsyncBaseTransport | None = None,
               engine_transport: httpx.AsyncBaseTransport | None = None,
               paylink_transport: httpx.AsyncBaseTransport | None = None) -> FastAPI:
    settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        async with httpx.AsyncClient(timeout=settings.auth_timeout_seconds, transport=transport,
                                     follow_redirects=False, trust_env=False) as client, \
                   httpx.AsyncClient(timeout=httpx.Timeout(settings.runtime_timeout_seconds, connect=10, pool=10),
                                     transport=transport, follow_redirects=False, trust_env=False) as runtime_http, \
                   httpx.AsyncClient(timeout=httpx.Timeout(settings.engine_timeout_seconds, connect=10, pool=10),
                                     transport=engine_transport, follow_redirects=False, trust_env=False) as engine_http, \
                   httpx.AsyncClient(timeout=12, transport=paylink_transport, follow_redirects=False,
                                     trust_env=False) as paylink_http:
            app.state.gateway = SupabaseGateway(settings, client)
            app.state.runtime_store = RuntimeStore(settings, runtime_http)
            app.state.engine_client = EngineClient(settings, engine_http)
            app.state.paylink_http = paylink_http
            yield

    app = FastAPI(title="Marketplace Backend 2", version="0.7.0", lifespan=lifespan)
    app.state.paylink_test = load_paylink_test(Path(__file__).resolve().parents[2])
    app.include_router(marketplace_router)
    app.include_router(execution_router)
    app.include_router(integrations_router)
    app.include_router(payments_router)
    app.add_middleware(BodySizeLimit)
    app.state.auth_limiter = AuthRateLimiter(settings.auth_requests_per_minute)
    app.add_middleware(CORSMiddleware, allow_origins=list(settings.cors_origins),
                      allow_credentials=False, allow_methods=["GET", "POST", "PATCH", "DELETE"],
                      allow_headers=["Authorization", "Content-Type"], expose_headers=["X-Request-ID", "Retry-After"])

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        request.state.request_id = uuid4().hex
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cache-Control"] = "no-store"
        response.headers["Pragma"] = "no-cache"
        return response

    @app.exception_handler(APIError)
    async def api_error(request: Request, error: APIError):
        payload = {"code": error.code, "message": error.message, "request_id": request.state.request_id}
        if error.details is not None:
            payload["details"] = error.details
        return JSONResponse(status_code=error.status, headers=error.headers,
                            content={"error": payload})

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, error: RequestValidationError):
        # FastAPI's default includes invalid input; never echo passwords/tokens.
        issues = [{"loc": list(issue["loc"]), "type": issue["type"]} for issue in error.errors()]
        return JSONResponse(status_code=422, content={"error": {"code": "validation_error",
            "message": "Проверьте поля запроса.", "request_id": request.state.request_id, "issues": issues}})

    async def limit_auth(request: Request):
        app.state.auth_limiter.check(request.client.host if request.client else "unknown")

    google_status: dict = {"checked_at": 0.0, "enabled": False}

    async def google_enabled(client: SupabaseGateway) -> bool:
        if time.monotonic() - google_status["checked_at"] > 30:
            result = await client.request("GET", "/auth/v1/settings")
            google_status.update(checked_at=time.monotonic(), enabled=(
                isinstance(result, dict) and result.get("external", {}).get("google") is True
            ))
        return google_status["enabled"]

    @app.get("/auth/providers", tags=["Auth"])
    async def providers(client: Annotated[SupabaseGateway, Depends(gateway)]):
        return {"google": await google_enabled(client)}

    @app.post("/auth/google/start", tags=["Auth"], dependencies=[Depends(limit_auth)])
    async def google_start(body: GoogleStartInput, client: Annotated[SupabaseGateway, Depends(gateway)]):
        redirect = urlsplit(body.redirect_to)
        origin = f"{redirect.scheme}://{redirect.netloc}"
        params = parse_qs(redirect.query, keep_blank_values=True)
        state = params.get("oauth_state", [])
        if (origin not in settings.oauth_redirect_origins or redirect.username or redirect.password
                or redirect.path != "/account/" or redirect.fragment or set(params) != {"oauth_state"}
                or len(state) != 1 or not re.fullmatch(r"[A-Za-z0-9_-]{43}", state[0])):
            raise APIError(422, "invalid_redirect", "Адрес возврата после входа не разрешён.")
        if not await google_enabled(client):
            raise APIError(503, "google_not_configured", "Вход через Google пока настраивается. Используйте почту и пароль.")
        query = urlencode({"provider": "google", "redirect_to": body.redirect_to,
                           "code_challenge": body.code_challenge, "code_challenge_method": "s256",
                           "scopes": "openid email profile", "prompt": "select_account"})
        return {"url": settings.supabase_url + "/auth/v1/authorize?" + query}

    @app.post("/auth/google/exchange", response_model=SessionResponse, tags=["Auth"], dependencies=[Depends(limit_auth)])
    async def google_exchange(body: GoogleExchangeInput, client: Annotated[SupabaseGateway, Depends(gateway)]):
        result = await client.request("POST", "/auth/v1/token", params={"grant_type": "pkce"}, operation="oauth",
                                      body={"auth_code": body.auth_code.get_secret_value(),
                                            "code_verifier": body.code_verifier.get_secret_value()})
        return await client.session_response(result)

    @app.get("/health", tags=["Monitoring"])
    async def health():
        return {"status": "ok", "service": "marketplace-backend-2", "version": "0.7.0"}

    def confirmation_redirect(request: Request) -> dict[str, str] | None:
        origin = request.headers.get("origin")
        if origin in settings.oauth_redirect_origins:
            return {"redirect_to": f"{origin}/account/?email_confirmation=1"}
        return None

    @app.post("/auth/signup", response_model=SignupResponse, status_code=201, tags=["Auth"], dependencies=[Depends(limit_auth)])
    async def signup(body: SignupInput, request: Request, client: Annotated[SupabaseGateway, Depends(gateway)]):
        payload = {"email": str(body.email), "password": body.password.get_secret_value(),
                   "data": {"role": body.role, "display_name": body.display_name, "company_name": body.company_name}}
        if body.captcha_token:
            payload["gotrue_meta_security"] = {"captcha_token": body.captcha_token.get_secret_value()}
        result = await client.request("POST", "/auth/v1/signup", body=payload, params=confirmation_redirect(request), operation="signup")
        if isinstance(result, dict) and result.get("access_token"):
            return SignupResponse(status="signed_in", session=await client.session_response(result))
        if not isinstance(result, dict):
            raise APIError(502, "supabase_contract_error", "Некорректный ответ сервиса авторизации.")
        return SignupResponse(status="confirmation_required")

    @app.post("/auth/email/resend", status_code=204, tags=["Auth"], dependencies=[Depends(limit_auth)])
    async def resend_email(body: ConfirmationEmail, request: Request, client: Annotated[SupabaseGateway, Depends(gateway)]):
        payload = {"email": str(body.email), "type": "signup"}
        if body.captcha_token:
            payload["gotrue_meta_security"] = {"captcha_token": body.captcha_token.get_secret_value()}
        await client.request("POST", "/auth/v1/resend", body=payload, params=confirmation_redirect(request), operation="resend")
        return Response(status_code=204)

    @app.post("/auth/email/verify", response_model=SessionResponse, tags=["Auth"], dependencies=[Depends(limit_auth)])
    async def verify_email(body: ConfirmationCode, client: Annotated[SupabaseGateway, Depends(gateway)]):
        result = await client.request("POST", "/auth/v1/verify", operation="verify_email",
                                      body={"email": str(body.email), "token": body.code.get_secret_value(), "type": "signup"})
        return await client.session_response(result)

    @app.post("/auth/login", response_model=SessionResponse, tags=["Auth"], dependencies=[Depends(limit_auth)])
    async def login(body: LoginInput, client: Annotated[SupabaseGateway, Depends(gateway)]):
        payload = {"email": str(body.email), "password": body.password.get_secret_value()}
        if body.captcha_token:
            payload["gotrue_meta_security"] = {"captcha_token": body.captcha_token.get_secret_value()}
        result = await client.request("POST", "/auth/v1/token", body=payload,
                                      params={"grant_type": "password"}, operation="login")
        return await client.session_response(result)

    @app.post("/auth/refresh", response_model=SessionResponse, tags=["Auth"], dependencies=[Depends(limit_auth)])
    async def refresh(body: RefreshInput, client: Annotated[SupabaseGateway, Depends(gateway)]):
        result = await client.request("POST", "/auth/v1/token", body={"refresh_token": body.refresh_token.get_secret_value()},
                                      params={"grant_type": "refresh_token"}, operation="refresh")
        return await client.session_response(result)

    @app.get("/auth/me", response_model=Principal, tags=["Profile"])
    async def me(user: Annotated[Principal, Depends(current_user)]):
        return user

    @app.patch("/auth/me", response_model=Principal, tags=["Profile"])
    async def update_me(body: ProfilePatch, user: Annotated[Principal, Depends(current_user)],
                        token: Annotated[str, Depends(current_token)], client: Annotated[SupabaseGateway, Depends(gateway)]):
        await client.request("PATCH", "/rest/v1/profiles", token=token,
                              params={"id": f"eq.{user.user_id}"}, body=body.model_dump(exclude_unset=True))
        return await client.authenticate(token)

    @app.post("/auth/logout", status_code=204, tags=["Auth"])
    async def logout(user: Annotated[Principal, Depends(current_user)], token: Annotated[str, Depends(current_token)],
                     client: Annotated[SupabaseGateway, Depends(gateway)]):
        await client.request("POST", "/auth/v1/logout", token=token, params={"scope": "local"})
        return Response(status_code=204)

    # Keep the existing external contract and provide same-origin browser APIs.
    browser_api = APIRouter()
    browser_api.routes.extend(route for route in app.routes if isinstance(route, APIRoute))
    app.include_router(browser_api, prefix="/api", include_in_schema=False)
    frontend = Path(__file__).resolve().parents[2] / "frontend" / "dist"
    if frontend.is_dir():
        app.mount("/", StaticFiles(directory=frontend, html=True), name="frontend")
    return app


# Uvicorn factory: --factory backend.app.main:create_app
