import json
from typing import Annotated
from uuid import UUID

from fastapi import Depends
from fastapi.testclient import TestClient
import httpx
import pytest

from backend.app.auth import require_roles
from backend.app.config import Settings
from backend.app.main import create_app
from backend.app.models import Principal
from starlette.routing import Mount

A = "00000000-0000-4000-8000-000000000001"
D = "00000000-0000-4000-8000-000000000002"
M = "00000000-0000-4000-8000-000000000003"
PASSWORD = "Example-password-2026"


class FakeSupabase:
    def __init__(self):
        self.requests = []
        self.overrides = {}
        self.sessions = {"a": True, "dev": True, "admin": True}
        self.profiles = {
            "a": {"id": A, "role": "business", "display_name": "A", "company_name": "Business A"},
            "dev": {"id": D, "role": "developer", "display_name": "D", "company_name": ""},
            "admin": {"id": M, "role": "admin", "display_name": "M", "company_name": ""},
        }

    def session(self, token="a"):
        return {"access_token": token, "refresh_token": f"refresh-{token}",
                "token_type": "bearer", "expires_in": 3600, "expires_at": 2000000000,
                "user": {"secret_metadata": "not-for-output"}}

    def __call__(self, request):
        self.requests.append(request)
        assert request.headers["apikey"] == "sb_publishable_test"
        assert "sb_secret_" not in str(request.headers)
        key = (request.method, request.url.path)
        if key in self.overrides:
            override = self.overrides[key]
            return override(request) if callable(override) else override
        token = request.headers.get("authorization", "").removeprefix("Bearer ")
        if request.url.path == "/auth/v1/signup":
            return httpx.Response(200, json={"id": A, "identities": []})
        if request.url.path == "/auth/v1/token":
            return httpx.Response(200, json=self.session())
        if request.url.path == "/auth/v1/user":
            if token not in self.profiles:
                return httpx.Response(401, json={"error_code": "bad_jwt"})
            return httpx.Response(200, json={"id": self.profiles[token]["id"], "email": "user@example.com",
                                           "user_metadata": {"role": "admin", "company_id": M}})
        if request.url.path == "/rest/v1/rpc/is_current_session_active":
            assert request.method == "POST" and json.loads(request.content) == {}
            return httpx.Response(200, json=self.sessions.get(token, False))
        if request.url.path == "/rest/v1/profiles":
            assert request.url.params["id"] == f"eq.{self.profiles[token]['id']}"
            if request.method == "PATCH":
                self.profiles[token].update(json.loads(request.content))
            return httpx.Response(200, json=[self.profiles[token]])
        if request.url.path == "/auth/v1/logout":
            assert request.url.params["scope"] == "local"
            self.sessions[token] = False
            return httpx.Response(204)
        raise AssertionError(f"Unexpected upstream call: {request.method} {request.url.path}")


@pytest.fixture
def environment():
    remote = FakeSupabase()
    settings = Settings(supabase_url="https://project.supabase.co", supabase_publishable_key="sb_publishable_test",
                        auth_requests_per_minute=100)
    app = create_app(settings, transport=httpx.MockTransport(remote))

    @app.get("/test/admin")
    async def admin(user: Annotated[Principal, Depends(require_roles("admin"))]):
        return {"id": str(user.user_id)}

    @app.get("/test/business")
    async def business(user: Annotated[Principal, Depends(require_roles("business"))]):
        return {"id": str(user.company_id)}

    # The production static site is mounted last. Test-only routes added afterwards
    # must precede that catch-all when frontend/dist exists on the developer machine.
    app.router.routes.sort(key=lambda route: isinstance(route, Mount))

    with TestClient(app) as client:
        yield client, remote


def auth(token="a"):
    return {"Authorization": f"Bearer {token}"}


def test_health_and_openapi(environment):
    client, remote = environment
    assert client.get("/health").json()["status"] == "ok"
    schema = client.get("/openapi.json").json()
    assert schema["paths"]["/auth/me"]["get"]["security"] == [{"HTTPBearer": []}]
    assert not remote.requests


@pytest.mark.parametrize("headers", [{}, {"Authorization": "Basic nope"}, auth("unknown"), auth("a b")])
def test_missing_malformed_and_invalid_tokens_are_rejected(environment, headers):
    client, _ = environment
    response = client.get("/auth/me", headers=headers)
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"
    assert response.json()["error"]["request_id"] == response.headers["X-Request-ID"]


def test_role_and_tenant_come_from_profile_not_user_metadata(environment):
    client, _ = environment
    profile = client.get("/auth/me", headers=auth()).json()
    assert profile["role"] == "business"
    assert profile["company_id"] == A
    assert "user_metadata" not in profile
    assert client.get("/test/admin", headers=auth()).status_code == 403
    assert client.get("/test/admin", headers=auth("admin")).status_code == 200
    assert client.get("/test/business", headers=auth("dev")).status_code == 403
    assert client.get("/auth/me", headers=auth("dev")).json()["company_id"] is None


def test_login_uses_password_grant_and_returns_only_allowlisted_session_fields(environment):
    client, remote = environment
    response = client.post("/auth/login", json={"email": "user@example.com", "password": PASSWORD})
    assert response.status_code == 200
    assert response.json()["profile"]["user_id"] == A
    assert response.json()["session"]["refresh_token"] == "refresh-a"
    assert "secret_metadata" not in response.text and PASSWORD not in response.text
    assert response.headers["Cache-Control"] == "no-store"
    assert remote.requests[0].url.params["grant_type"] == "password"
    assert json.loads(remote.requests[0].content)["password"] == PASSWORD


@pytest.mark.parametrize("role", ["business", "developer"])
def test_signup_preserves_email_confirmation_and_allowlisted_role(environment, role):
    client, remote = environment
    response = client.post("/auth/signup", json={"email": "user@example.com", "password": PASSWORD,
        "role": role, "display_name": " Alice ", "company_name": " Acme "})
    assert response.status_code == 201
    assert response.json() == {"status": "confirmation_required", "session": None}
    assert json.loads(remote.requests[0].content)["data"] == {"role": role, "display_name": "Alice", "company_name": "Acme"}


def test_signup_supports_session_when_project_does_not_require_confirmation(environment):
    client, remote = environment
    remote.overrides[("POST", "/auth/v1/signup")] = httpx.Response(200, json=remote.session())
    response = client.post("/auth/signup", json={"email": "user@example.com", "password": PASSWORD})
    assert response.status_code == 201
    assert response.json()["status"] == "signed_in"


def test_confirmation_resend_uses_allowlisted_redirect_and_reports_unavailable_email(environment):
    client, remote = environment
    email = {"email": "user@example.com"}
    route = "/auth/v1/resend"
    remote.overrides[("POST", route)] = httpx.Response(200, json={})
    response = client.post("/auth/email/resend", json=email, headers={"Origin": "http://localhost:3000"})
    assert response.status_code == 204
    assert remote.requests[-1].url.params["redirect_to"] == "http://localhost:3000/account/?email_confirmation=1"
    assert json.loads(remote.requests[-1].content) == {**email, "type": "signup"}

    response = client.post("/auth/email/resend", json=email, headers={"Origin": "https://untrusted.example"})
    assert response.status_code == 204 and "redirect_to" not in remote.requests[-1].url.params

    remote.overrides[("POST", route)] = httpx.Response(403, json={"error_code": "email_address_not_authorized"})
    response = client.post("/auth/email/resend", json=email)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "confirmation_email_unavailable"


def test_confirmation_code_starts_session_and_expired_code_is_not_leaked(environment):
    client, remote = environment
    data = {"email": "user@example.com", "code": "012345"}
    route = "/auth/v1/verify"
    remote.overrides[("POST", route)] = httpx.Response(200, json=remote.session())
    response = client.post("/api/auth/email/verify", json=data)
    assert response.status_code == 200 and response.json()["profile"]["user_id"] == A
    assert json.loads(remote.requests[0].content) == {"email": data["email"], "token": data["code"], "type": "signup"}
    assert response.headers["Cache-Control"] == "no-store"

    remote.overrides[("POST", route)] = httpx.Response(403, json={"error_code": "otp_expired", "message": data["code"]})
    response = client.post("/api/auth/email/verify", json=data)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_confirmation_code"
    assert data["code"] not in response.text


@pytest.mark.parametrize("route,upstream,fields", [
    ("/auth/signup", "/auth/v1/signup", {"password": PASSWORD}),
    ("/auth/email/resend", "/auth/v1/resend", {}),
])
def test_confirmation_mailer_failure_has_specific_safe_message(environment, route, upstream, fields):
    client, remote = environment
    remote.overrides[("POST", upstream)] = httpx.Response(500, json={
        "error_code": "unexpected_failure", "msg": "Error sending confirmation email",
        "internal_error": "SMTP authentication failed: private provider detail",
    })
    response = client.post(route, json={"email": "user@example.com", **fields})
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "confirmation_email_unavailable"
    assert "Не удалось отправить письмо подтверждения" in response.json()["error"]["message"]
    assert "private provider detail" not in response.text


@pytest.mark.parametrize("extra", [{"role": "admin"}, {"company_id": M}, {"user_id": M}, {"password": "short"}])
def test_signup_cannot_escalate_or_inject_identity_and_never_echoes_secrets(environment, extra):
    client, remote = environment
    response = client.post("/auth/signup", json={"email": "user@example.com", "password": PASSWORD, **extra})
    assert response.status_code == 422
    assert PASSWORD not in response.text and '"short"' not in response.text
    assert not remote.requests


def test_refresh_rotates_session_using_refresh_grant(environment):
    client, remote = environment
    response = client.post("/auth/refresh", json={"refresh_token": "refresh-before"})
    assert response.status_code == 200
    assert remote.requests[0].url.params["grant_type"] == "refresh_token"
    assert json.loads(remote.requests[0].content) == {"refresh_token": "refresh-before"}


def test_logout_revokes_current_session_and_rejects_old_access_token(environment):
    client, remote = environment
    assert client.post("/auth/logout", headers=auth()).status_code == 204
    response = client.get("/auth/me", headers=auth())
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "session_revoked"
    assert remote.sessions["dev"] is True


def test_profile_edit_cannot_change_role_identity_or_company_id(environment):
    client, _ = environment
    assert client.patch("/auth/me", headers=auth(), json={"display_name": "New"}).json()["display_name"] == "New"
    for patch in [{"role": "admin"}, {"company_id": M}, {"id": M}, {"display_name": None}, {}]:
        assert client.patch("/auth/me", headers=auth(), json=patch).status_code == 422


@pytest.mark.parametrize("status,code,expected,public_code", [
    (400, "invalid_credentials", 401, "invalid_credentials"),
    (400, "email_not_confirmed", 403, "email_not_confirmed"),
    (429, "over_request_rate_limit", 429, "auth_rate_limited"),
    (500, "unexpected_failure", 503, "supabase_unavailable"),
])
def test_login_errors_are_stable_and_do_not_leak_provider_details(environment, status, code, expected, public_code):
    client, remote = environment
    remote.overrides[("POST", "/auth/v1/token")] = httpx.Response(status, headers={"Retry-After": "42"},
        json={"error_code": code, "msg": f"private provider detail {PASSWORD}"})
    response = client.post("/auth/login", json={"email": "user@example.com", "password": PASSWORD})
    assert response.status_code == expected
    assert response.json()["error"]["code"] == public_code
    assert PASSWORD not in response.text and "private provider" not in response.text
    if status == 429:
        assert response.headers["Retry-After"] == "42"


def test_duplicate_signup_does_not_disclose_account_existence(environment):
    client, remote = environment
    remote.overrides[("POST", "/auth/v1/signup")] = httpx.Response(422, json={"error_code": "user_already_exists"})
    assert client.post("/auth/signup", json={"email": "user@example.com", "password": PASSWORD}).json() == {
        "status": "confirmation_required", "session": None}


def test_network_failures_and_bad_upstream_payload_fail_closed(environment):
    client, remote = environment
    def timeout(request):
        raise httpx.ReadTimeout("secret detail", request=request)
    remote.overrides[("GET", "/auth/v1/user")] = timeout
    assert client.get("/auth/me", headers=auth()).status_code == 503
    for payload in [[], {"id": "invalid"}, {"email": "test@example.com"}]:
        remote.overrides[("GET", "/auth/v1/user")] = httpx.Response(200, json=payload)
        assert client.get("/auth/me", headers=auth()).status_code == 502
    remote.overrides.pop(("GET", "/auth/v1/user"))
    remote.overrides[("GET", "/rest/v1/profiles")] = httpx.Response(200, json=[{**remote.profiles["a"], "id": D}])
    assert client.get("/auth/me", headers=auth()).status_code == 502


def test_missing_profile_and_anonymous_user_cannot_access_platform(environment):
    client, remote = environment
    remote.overrides[("GET", "/rest/v1/profiles")] = httpx.Response(200, json=[])
    assert client.get("/auth/me", headers=auth()).json()["error"]["code"] == "profile_missing"
    remote.overrides[("GET", "/auth/v1/user")] = httpx.Response(200, json={"id": A, "is_anonymous": True})
    assert client.get("/auth/me", headers=auth()).status_code == 401


def test_rate_limit_is_applied_before_contacting_supabase():
    remote = FakeSupabase()
    settings = Settings(supabase_url="https://project.supabase.co", supabase_publishable_key="sb_publishable_test", auth_requests_per_minute=1)
    with TestClient(create_app(settings, transport=httpx.MockTransport(remote))) as client:
        body = {"email": "user@example.com", "password": PASSWORD}
        assert client.post("/auth/login", json=body).status_code == 200
        calls = len(remote.requests)
        response = client.post("/auth/login", json=body)
        assert response.status_code == 429 and int(response.headers["Retry-After"]) > 0
        assert len(remote.requests) == calls


def test_cors_only_allows_configured_frontend(environment):
    client, _ = environment
    headers = {"Origin": "http://localhost:3000", "Access-Control-Request-Method": "POST"}
    assert client.options("/auth/login", headers=headers).headers["access-control-allow-origin"] == "http://localhost:3000"
    headers["Origin"] = "https://untrusted.example.com"
    assert "access-control-allow-origin" not in client.options("/auth/login", headers=headers).headers


@pytest.mark.parametrize("url,key", [
    ("http://external.example.com", "sb_publishable_test"),
    ("https://user:password@project.supabase.co", "sb_publishable_test"),
    ("https://project.supabase.co", "sb_secret_forbidden"),
])
def test_configuration_rejects_insecure_url_and_privileged_key(url, key):
    with pytest.raises(ValueError) as error:
        Settings(supabase_url=url, supabase_publishable_key=key)
    assert key not in str(error.value)
