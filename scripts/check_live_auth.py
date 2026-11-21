"""Explicit live test using a disposable, pre-confirmed test user; sends no email.

Usage: python scripts/check_live_auth.py .run/auth-smoke.json
Credential file keys: user_id, email, password. Never print the file or tokens.
Creation and cleanup of the test user are handled by the test operator.
"""
import json
from pathlib import Path
import sys

from fastapi.testclient import TestClient

from backend.app.main import create_app


def main():
    credentials = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    checks = []

    def expect(response, status, step):
        if response.status_code != status:
            data = response.json()
            code = data.get("error", {}).get("code", "unknown")
            raise RuntimeError(f"{step}: expected {status}, got {response.status_code}, code={code}")
        checks.append(step)
        return response

    with TestClient(create_app()) as client:
        expect(client.get("/health"), 200, "health")
        expect(client.get("/auth/me"), 401, "missing_token_rejected")
        expect(client.post("/auth/signup", json={"email": credentials["email"], "password": credentials["password"], "role": "admin"}),
               422, "admin_signup_rejected_before_auth")
        expect(client.post("/auth/login", json={"email": credentials["email"], "password": "incorrect-test-password"}),
               401, "wrong_password_rejected")
        login = expect(client.post("/auth/login", json={"email": credentials["email"], "password": credentials["password"]}),
                       200, "password_login").json()
        assert login["profile"]["user_id"] == credentials["user_id"]
        assert login["profile"]["role"] == "business"
        token = login["session"]["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        expect(client.get("/auth/me", headers=headers), 200, "authenticated_profile")
        profile = expect(client.patch("/auth/me", headers=headers, json={"display_name": "Temporary Auth Test"}),
                         200, "profile_update").json()
        assert profile["display_name"] == "Temporary Auth Test"
        expect(client.patch("/auth/me", headers=headers, json={"role": "admin"}), 422, "profile_role_escalation_rejected")
        refreshed = expect(client.post("/auth/refresh", json={"refresh_token": login["session"]["refresh_token"]}),
                           200, "session_refresh").json()
        fresh_headers = {"Authorization": f"Bearer {refreshed['session']['access_token']}"}
        expect(client.post("/auth/logout", headers=fresh_headers), 204, "current_session_logout")
        expect(client.get("/auth/me", headers=headers), 401, "old_access_token_revoked")
        expect(client.get("/auth/me", headers=fresh_headers), 401, "refreshed_access_token_revoked")
        expect(client.post("/auth/refresh", json={"refresh_token": refreshed["session"]["refresh_token"]}),
               401, "refresh_after_logout_rejected")
    print(json.dumps({"passed": len(checks), "checks": checks, "signup_email_delivery_tested": False}))


if __name__ == "__main__":
    main()
