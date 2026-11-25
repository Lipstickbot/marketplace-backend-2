"""Live integration test with one disposable, pre-confirmed business account.

Requires prior authorization to create/delete a temporary test account and data.
Uses real Supabase Auth/Storage/PostgreSQL and the configured mock AI Engine.
Credentials stay in memory. A cleanup manifest contains only the test UUID.
Engine files are deleted, but its technical run/tenant records have no delete API.
"""
import json
from pathlib import Path
import secrets
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
import httpx

from backend.app.config import Settings
from backend.app.engine_client import EngineClient
from backend.app.main import create_app
from backend.app.models import Principal


def main(backend_url=None):
    root = Path(__file__).resolve().parents[1]
    settings = Settings.from_env()
    if backend_url:
        parsed = httpx.URL(backend_url)
        if parsed.scheme != 'https' or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise RuntimeError('Public backend URL must use HTTPS without credentials, query or fragment')
    if not settings.supabase_secret_key:
        raise RuntimeError("Server key is not configured")
    for fixture in ["fictional-resume.docx", "fictional-brief.pdf"]:
        if not (root / ".run" / "fixtures" / fixture).exists():
            raise RuntimeError("Generate synthetic fixtures first")
    checks = []
    manifest = root / ".run" / "cloud-engine-cleanup.json"
    if manifest.exists():
        raise RuntimeError("A previous live test needs cleanup; do not create another account")
    user_id = None
    password = secrets.token_urlsafe(48)
    email = f"engine-check-{uuid4().hex}@example.com"

    def checked(response, status, step):
        statuses = {status} if isinstance(status, int) else set(status)
        if response.status_code not in statuses:
            raise RuntimeError(f"{step}: unexpected HTTP {response.status_code}")
        checks.append(step)
        return response

    with httpx.Client(base_url=settings.supabase_url, timeout=60, trust_env=False,
            headers={"apikey": settings.supabase_secret_key.get_secret_value()}) as admin, \
         httpx.Client(base_url=settings.engine_url, timeout=settings.engine_timeout_seconds, trust_env=False) as engine, \
         (httpx.Client(base_url=backend_url, timeout=180, trust_env=False) if backend_url else TestClient(create_app(settings))) as api:
        health = checked(api.get("/engine/health"), 200, "engine_health").json()
        if health["llm_provider"] != "mock":
            raise RuntimeError("Live test is restricted to the mock LLM")
        try:
            created = checked(admin.post("/auth/v1/admin/users", json={
                "email": email, "password": password, "email_confirm": True,
                "user_metadata": {"role": "business", "display_name": "Disposable Engine Check", "company_name": "Fictional Cloud Company"}
            }), (200, 201), "temporary_account_created").json()
            user_id = str(UUID(created["id"]))
            manifest.write_text(json.dumps({"user_id": user_id, "email": email}), encoding="utf-8")
            login = checked(api.post("/auth/login", json={"email": email, "password": password}), 200, "supabase_login").json()
            assert login["profile"]["user_id"] == user_id and login["profile"]["role"] == "business"
            headers = {"Authorization": f"Bearer {login['session']['access_token']}"}
            checked(api.post("/agents/marketing/run", headers=headers, json={"message": "Test without approval"}),
                    403, "unapproved_execution_rejected")
            cards = checked(api.get("/agents"), 200, "cloud_catalog").json()["items"]
            for slug in ["marketing", "support", "hr"]:
                card = next(item for item in cards if item["engine_slug"] == slug and item["status"] == "published")
                connection = checked(api.post("/connect-requests", headers=headers, json={"agent_id": card["id"]}),
                                     201, "business_connection_request").json()
                assert connection["status"] == "approved" and connection["reviewed_by"] is None

            result = checked(api.post("/agents/marketing/run", headers=headers, json={
                "message": "Create a content plan for a fictional coffee shop.", "language": "en"}), 200, "marketing_cloud_audit").json()
            assert result["audit_saved"] is True and result["execution"]["mode"] == "mock"

            documents = [
                ("knowledge.txt", "knowledge_base", "Доставка по городу стоит 1000 тенге. Доставка занимает два дня.".encode(), "text/plain"),
                ("resume.docx", "resume", (root / ".run/fixtures/fictional-resume.docx").read_bytes(), "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
                ("brief.pdf", "brief", (root / ".run/fixtures/fictional-brief.pdf").read_bytes(), "application/pdf"),
            ]
            files = {}
            for filename, purpose, content, mime in documents:
                row = checked(api.post("/files/upload", headers=headers, data={"purpose": purpose}, files={
                    "file": (filename, content, mime)}), 201, f"cloud_upload_{purpose}").json()
                files[purpose] = row
                downloaded = checked(api.get(f"/files/{row['id']}/download", headers=headers), 200, f"cloud_download_{purpose}")
                assert downloaded.content == content and row["engine_file_id"]

            support = checked(api.post("/agents/support/run", headers=headers, json={"message": "Сколько стоит доставка?",
                "language": "ru", "file_ids": [files["knowledge_base"]["id"]]}), 200, "support_real_rag_cloud_audit").json()
            assert support["audit_saved"] is True and support["execution"]["sources"]
            hr = checked(api.post("/agents/hr/run", headers=headers, json={"message": "Summarize the uploaded resume.",
                "language": "en", "options": {"task": "resume_summary"}, "file_ids": [files["resume"]["id"]]}), 200, "hr_docx_cloud_audit").json()
            assert hr["audit_saved"] is True
            pdf = checked(api.post("/agents/marketing/run", headers=headers, json={"message": "Create a content plan from the attached brief.",
                "language": "en", "file_ids": [files["brief"]["id"]]}), 200, "marketing_pdf_cloud_audit").json()
            assert pdf["audit_saved"] is True
            error = checked(api.post("/agents/hr/run", headers=headers, json={"message": "Summarize the uploaded resume.",
                "options": {"task": "resume_summary"}}), 422, "engine_error_cloud_audit").json()
            assert error["error"]["details"]["audit_saved"] is True
            history = checked(api.get("/runs", headers=headers), 200, "cloud_run_history").json()["items"]
            assert len(history) == 5 and sum(item["status"] == "success" for item in history) == 4
            assert all("response" not in item and "message" not in item for item in history)
            application = checked(api.post("/integrations", headers=headers, json={
                "agent_slug": "support", "name": "Disposable application integration", "task": "Answer delivery questions for a fictional shop.",
                "language": "ru", "file_ids": [files["knowledge_base"]["id"]], "expires_in_days": 1
            }), 201, "scoped_application_key_created").json()
            key = application["api_key"]
            application_headers = {"Authorization": "Bearer " + key}
            model_list = checked(api.get("/v1/models", headers=application_headers), 200, "scoped_model_list").json()
            assert [item["id"] for item in model_list["data"]] == ["keme/support"]
            listed = checked(api.get("/integrations", headers=headers), 200, "safe_application_list")
            assert key not in listed.text and "key_hash" not in listed.text
            request_body = {"model": "keme/support", "messages": [{"role": "user", "content": "Сколько стоит доставка?"}], "stream": False}
            completion = checked(api.post("/v1/chat/completions", headers=application_headers, json=request_body),
                                 200, "application_real_rag_execution").json()
            assert completion["choices"][0]["message"]["content"] and completion["keme"]["audit_saved"] is True and completion["keme"]["mode"] == "mock"
            checked(api.post("/v1/chat/completions", headers=application_headers, json={**request_body, "model": "keme/hr"}),
                    403, "application_model_scope_enforced")
            checked(api.delete("/integrations/" + application["integration"]["id"], headers=headers), 204, "application_key_revoked")
            checked(api.post("/v1/chat/completions", headers=application_headers, json=request_body), 401, "revoked_application_key_rejected")
            for row in files.values():
                checked(api.delete(f"/files/{row['id']}", headers=headers), 204, "both_file_copies_deleted")
                checked(api.get(f"/files/{row['id']}", headers=headers), 404, "deleted_file_unavailable")
            checked(api.post("/auth/logout", headers=headers), 204, "test_session_revoked")
        finally:
            if user_id:
                # Cleanup is strictly restricted to the newly created test UUID.
                principal = Principal(user_id=UUID(user_id), email=None, role="business", company_id=UUID(user_id),
                                      display_name="Disposable Engine Check", company_name="Fictional Cloud Company")
                engine_headers = {"Authorization": f"Bearer {EngineClient(settings, None).token(principal)}"}
                remaining = checked(engine.get("/files", headers=engine_headers), 200, "cleanup_engine_files_list").json()["files"]
                for row in remaining:
                    checked(engine.delete(f"/files/{UUID(row['id'])}", headers=engine_headers), (204, 404), "cleanup_engine_file")
                own = {"company_id": f"eq.{user_id}", "user_id": f"eq.{user_id}"}
                rows = checked(admin.get("/rest/v1/agent_files", params={**own, "select": "object_path"}), 200, "cleanup_cloud_files_list").json()
                if rows:
                    paths = [row["object_path"] for row in rows]
                    assert all(path.startswith(f"{user_id}/{user_id}/") for path in paths)
                    checked(admin.request("DELETE", "/storage/v1/object/agent-files", json={"prefixes": paths}), (200, 204), "cleanup_storage_objects")
                for table in ["agent_integrations", "agent_files", "agent_runs"]:
                    checked(admin.delete(f"/rest/v1/{table}", params=own), 204, f"cleanup_{table}")
                checked(admin.delete("/rest/v1/connect_requests", params={"company_id": f"eq.{user_id}", "requested_by": f"eq.{user_id}"}),
                        204, "cleanup_connection_fixtures")
                checked(admin.request("DELETE", f"/auth/v1/admin/users/{user_id}", json={"should_soft_delete": False}),
                        (200, 404), "temporary_account_deleted")
                checked(admin.get(f"/auth/v1/admin/users/{user_id}"), 404, "temporary_account_absent")
                manifest.unlink(missing_ok=True)
    report = {"passed": len(checks), "supabase": "real Auth/Storage/PostgreSQL", "engine": settings.engine_url,
              "backend": backend_url or "in-process TestClient",
              "llm_mode": "mock", "test_account_deleted": True,
              "engine_technical_metadata_retained": True, "checks": checks}
    (root / ".run" / "cloud-engine-report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print({key: value for key, value in report.items() if key != "checks"})


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backend-url', help='Published HTTPS Backend URL; omitted uses in-process TestClient')
    main(parser.parse_args().backend_url)
