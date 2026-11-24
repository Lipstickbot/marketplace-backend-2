import json
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from backend.tests.test_auth import environment, A

CHALLENGE = "A" * 43
REDIRECT = "https://keme-ai-platform.onrender.com/account/?oauth_state=" + "B" * 43


def enable_google(remote, enabled=True):
    remote.overrides[("GET", "/auth/v1/settings")] = httpx.Response(200, json={"external": {"google": enabled}})


def test_google_start_is_pkce_and_redirect_allowlisted(environment):
    client, remote = environment
    enable_google(remote)
    result = client.post("/api/auth/google/start", json={"code_challenge": CHALLENGE, "redirect_to": REDIRECT})
    assert result.status_code == 200
    url = urlsplit(result.json()["url"])
    assert url.scheme == "https" and url.netloc == "project.supabase.co" and url.path == "/auth/v1/authorize"
    params = parse_qs(url.query)
    assert params["provider"] == ["google"]
    assert params["redirect_to"] == [REDIRECT]
    assert params["code_challenge_method"] == ["s256"]
    assert params["code_challenge"] == [CHALLENGE]
    assert params["scopes"] == ["openid email profile"]
    assert "code_verifier" not in params


@pytest.mark.parametrize("redirect", [
    "https://evil.example/account/?oauth_state=" + "B" * 43,
    "https://keme-ai-platform.onrender.com.evil.example/account/?oauth_state=" + "B" * 43,
    "https://keme-ai-platform.onrender.com/account/?oauth_state=" + "B" * 43 + "&next=https://evil.example",
    "https://keme-ai-platform.onrender.com/account/?oauth_state=bad",
    "https://keme-ai-platform.onrender.com/account/?oauth_state=" + "B" * 43 + "#token",
    "https://keme-ai-platform.onrender.com/other/?oauth_state=" + "B" * 43,
])
def test_google_rejects_redirect_injection(environment, redirect):
    client, remote = environment
    result = client.post("/auth/google/start", json={"code_challenge": CHALLENGE, "redirect_to": redirect})
    assert result.status_code == 422
    assert not remote.requests


def test_disabled_google_keeps_password_login_available(environment):
    client, remote = environment
    enable_google(remote, False)
    assert client.get("/auth/providers").json() == {"google": False}
    result = client.post("/auth/google/start", json={"code_challenge": CHALLENGE, "redirect_to": REDIRECT})
    assert result.status_code == 503 and result.json()["error"]["code"] == "google_not_configured"
    assert client.post("/auth/login", json={"email": "user@example.com", "password": "test-password"}).status_code == 200


def test_google_exchange_uses_verified_database_role(environment):
    client, remote = environment
    response = client.post("/auth/google/exchange", json={"auth_code": "one-use-code", "code_verifier": "x" * 64})
    assert response.status_code == 200
    upstream = remote.requests[0]
    assert upstream.url.params["grant_type"] == "pkce"
    assert json.loads(upstream.content) == {"auth_code": "one-use-code", "code_verifier": "x" * 64}
    assert response.json()["profile"]["role"] == "business"
    assert response.json()["profile"]["company_id"] == A
    assert "secret_metadata" not in response.text


def test_google_invalid_exchange_does_not_echo_credentials(environment):
    client, remote = environment
    remote.overrides[("POST", "/auth/v1/token")] = httpx.Response(400, json={"msg": "code-verifier-secret"})
    result = client.post("/auth/google/exchange", json={"auth_code": "code-secret", "code_verifier": "code-verifier-secret" * 4})
    assert result.status_code == 400
    assert "code-verifier-secret" not in result.text and "code-secret" not in result.text


def test_google_verifier_validation_hides_secrets(environment):
    client, remote = environment
    result = client.post("/auth/google/exchange", json={"auth_code": "private-code", "code_verifier": "bad verifier with spaces" * 3})
    assert result.status_code == 422 and "private-code" not in result.text
    assert not remote.requests
