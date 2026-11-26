import asyncio
import re
import time
from uuid import NAMESPACE_URL, UUID, uuid5

import httpx
import jwt

from .config import Settings
from .errors import APIError
from .models import Principal


CATALOG_ID = str(uuid5(NAMESPACE_URL, "https://keme-ai.onrender.com/moderation"))


class EngineError(APIError):
    def __init__(self, status, code, *, run_id: str | None = None, headers=None, source_status: int | None = None):
        super().__init__(status, code, "Не удалось выполнить запрос к AI Engine.", headers)
        self.run_id = run_id
        self.source_status = source_status


class EngineClient:
    def __init__(self, settings: Settings, client: httpx.AsyncClient):
        self.settings = settings
        self.client = client

    def token(self, user: Principal) -> str:
        if user.role != "business" or user.company_id is None:
            raise APIError(403, "role_forbidden", "Доступно только бизнесу.")
        return self._sign(str(user.user_id), str(user.company_id), "admin", user.company_name)

    def _sign(self, user_id: str, company_id: str, role: str, company_name: str) -> str:
        if not self.settings.engine_jwt_secret:
            raise APIError(503, "engine_not_configured", "Не настроен секрет AI Engine.")
        now = int(time.time())
        return jwt.encode({"sub": user_id, "company_id": company_id, "role": role,
                           "company_name": company_name, "aud": self.settings.engine_jwt_audience,
                           "iss": self.settings.engine_jwt_issuer, "iat": now,
                           "exp": now + self.settings.engine_jwt_ttl_seconds},
                          self.settings.engine_jwt_secret.get_secret_value(), algorithm="HS256")

    async def request(self, method, path, user: Principal | None = None, **kwargs):
        return await self._request(method, path, self.token(user) if user else None, **kwargs)

    async def agent_metadata(self, slug: str):
        token = self._sign(CATALOG_ID, CATALOG_ID, "member", "Keme AI catalog verification")
        return await self._request("GET", f"/agents/{slug}", token)

    async def _request(self, method, path, token, **kwargs):
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        try:
            async with asyncio.timeout(self.settings.engine_timeout_seconds):
                response = await self.client.request(method, self.settings.engine_url + path, headers=headers, **kwargs)
        except (TimeoutError, httpx.TimeoutException):
            raise EngineError(504, "engine_timeout") from None
        except httpx.RequestError:
            raise EngineError(503, "engine_unreachable") from None
        if response.status_code == 204:
            return None
        try:
            data = response.json()
        except ValueError:
            raise EngineError(502, "engine_invalid_response", source_status=response.status_code) from None
        if response.status_code >= 400:
            error = data.get("error", {}) if isinstance(data, dict) else {}
            error = error if isinstance(error, dict) else {}
            raw_code = error.get("code")
            code = raw_code if isinstance(raw_code, str) and re.fullmatch(r"[a-z][a-z0-9_]{0,119}", raw_code) else "request_failed"
            detail = error.get("details")
            run_id = detail.get("run_id") if isinstance(detail, dict) else None
            try:
                run_id = str(UUID(run_id)) if isinstance(run_id, str) else None
            except ValueError:
                run_id = None
            retry = response.headers.get("Retry-After", "")
            retry_headers = {"Retry-After": retry} if retry.isdecimal() and len(retry) < 8 else {}
            status = response.status_code if response.status_code in {403, 404, 413, 415, 422, 429, 502, 503, 504} else 502
            if response.status_code == 401:
                code = "authentication_failed"
            raise EngineError(status, f"engine_{code}", run_id=run_id, headers=retry_headers, source_status=response.status_code)
        if not 200 <= response.status_code < 300:
            raise EngineError(502, "engine_invalid_response")
        return data
