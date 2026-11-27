import json

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.app import architect
from backend.app.config import Settings
from backend.app.main import create_app
from backend.tests.test_auth import M, auth
from backend.tests.test_execution import RuntimeFake
from backend.tests.test_marketplace import SUBMISSION, submission


@pytest.fixture
def platform(monkeypatch):
    monkeypatch.setattr(architect, "instructions", lambda: "Reviewed ARCHITECT requirements guidance")
    remote = RuntimeFake()
    repository = "https://github.com/Bigfigboy/ARCHITECT-AI-Systems-Business-Analyst"
    remote.records["agent_submissions"] = [submission(repository_url=repository)]
    calls, reviews = [], []
    model = {"status": 200, "data": {"candidates": [
        {"content": {"parts": [{"text": "Acceptance criteria make a requirement testable."}]}, "finishReason": "STOP"}
    ], "usageMetadata": {"promptTokenCount": 15, "candidatesTokenCount": 7, "thoughtsTokenCount": 3}}}

    def provider(request):
        assert request.url.host == "generativelanguage.googleapis.com"
        assert request.url.path.endswith(":generateContent")
        assert request.headers["x-goog-api-key"] == "test-gemini"
        calls.append(json.loads(request.content))
        return httpx.Response(model["status"], json=model["data"])

    def supabase(request):
        if request.url.path.endswith("/rpc/activate_agent_submission"):
            assert request.headers["apikey"] == "sb_secret_test"
            reviews.append(json.loads(request.content))
            return httpx.Response(200, json=submission(repository_url=repository, status="approved", reviewed_by=M))
        return remote(request)

    def external_engine(request):
        pytest.fail("ARCHITECT used the external AI Engine")

    settings = Settings(supabase_url="https://project.supabase.co", supabase_publishable_key="sb_publishable_test",
                        supabase_secret_key="sb_secret_test", architect_gemini_api_key="test-gemini")
    with TestClient(create_app(settings, transport=httpx.MockTransport(supabase),
        engine_transport=httpx.MockTransport(external_engine), architect_transport=httpx.MockTransport(provider))) as client:
        yield client, remote, calls, reviews, model


def review(client, slug=architect.SLUG):
    return client.post(f"/api/admin/agent-submissions/{SUBMISSION}/review", headers=auth("admin"),
                       json={"decision": "approved", "engine_slug": slug})


def test_known_submission_verifies_runtime_before_activation(platform):
    client, _, calls, reviews, _ = platform
    rejected = review(client, "business-analytics")
    assert rejected.status_code == 422 and rejected.json()["error"]["code"] == "architect_slug_required"
    assert not calls and not reviews
    accepted = review(client)
    assert accepted.status_code == 200, accepted.text
    assert len(calls) == len(reviews) == 1
    assert "Reviewed ARCHITECT" in calls[0]["systemInstruction"]["parts"][0]["text"]
    assert reviews[0]["p_actor"] == M
    assert reviews[0]["p_card"]["engine_slug"] == reviews[0]["p_card"]["slug"] == architect.SLUG


def test_architect_slug_cannot_activate_an_unrelated_submission(platform):
    client, remote, calls, reviews, _ = platform
    remote.records["agent_submissions"][0]["repository_url"] = "https://github.com/other/project"
    response = review(client)
    assert response.status_code == 422 and response.json()["error"]["code"] == "architect_repository_mismatch"
    assert not calls and not reviews


def test_missing_key_and_unavailable_model_preserve_pending_submission(platform):
    client, _, calls, reviews, model = platform
    model.update(status=403, data={"error": "private provider detail"})
    response = review(client)
    assert response.status_code == 503 and "private provider detail" not in response.text
    assert len(calls) == 1 and not reviews
    engine = client.app.state.engine_client
    engine.settings = engine.settings.model_copy(update={"architect_gemini_api_key": None})
    response = review(client)
    assert response.status_code == 503 and response.json()["error"]["code"] == "architect_not_configured"
    assert len(calls) == 1 and not reviews


def test_text_execution_enforces_business_access_and_records_gemini_usage(platform):
    client, remote, calls, _, _ = platform
    remote.records["agents"][0].update(slug=architect.SLUG, engine_slug=architect.SLUG, accepted_file_purposes=[])
    request = {"message": "Review this requirement.", "language": "en",
               "history": [{"role": "assistant", "content": "Send the requirement."}]}
    url = f"/api/agents/{architect.SLUG}/run"
    remote.records["connect_requests"][0]["status"] = "pending"
    assert client.post(url, headers=auth(), json=request).status_code == 403
    assert not calls
    remote.records["connect_requests"][0]["status"] = "approved"
    response = client.post(url, headers=auth(), json=request)
    assert response.status_code == 200, response.text
    output = response.json()["execution"]
    assert output["mode"] == "gemini" and output["usage"]["total_tokens"] == 25
    assert calls[0]["contents"][0]["role"] == "model"
    assert "Answer in English" in calls[0]["systemInstruction"]["parts"][0]["text"]
    row = remote.records["agent_runs"][0]
    assert row["engine_run_id"] is None and row["mode"] == "gemini"
    assert "Review this requirement" not in json.dumps(row)
