import asyncio
import json

import httpx
import pytest

from backend.app import business_analytics
from backend.tests.test_auth import auth
from backend.tests.test_execution import environment  # shared platform, Supabase and Engine fixtures
from backend.tests.test_integrations import environment as integration_environment
from backend.tests.test_marketplace import card
from scripts.deploy_business_analytics import activate_healthy

SLUG = business_analytics.SLUG
LEGACY_SLUG = business_analytics.LEGACY_SLUG
URL = f"/api/agents/{SLUG}/run"


@pytest.fixture
def analytics(environment):
    client, remote, engine = environment
    remote.records["agents"][0].update(slug=SLUG, engine_slug=SLUG, accepted_file_purposes=[])
    return client, remote, engine


@pytest.mark.parametrize("filename, separator", [("report.csv", ","), ("report.tsv", "\t")])
def test_analytics_runs_locally_and_audits(analytics, filename, separator):
    client, remote, engine = analytics
    assert client.get(f"/api/agents/{SLUG}").status_code == 200
    reply = client.post(URL, headers=auth(), json={"message": "Посчитай прибыль", "language": "ru",
        "dataset": {"filename": filename, "text": f"revenue{separator}cost\n100{separator}40\n"}})
    assert reply.status_code == 200, reply.text
    result = reply.json()
    assert result["execution"]["data"]["metrics"]["profit"]["value"] == "60"
    row = remote.records["agent_runs"][0]
    assert row["id"] == result["platform_run_id"] and row["engine_run_id"] is None
    assert row["status"] == "success" and row["file_count"] == 1
    assert "100" not in str(row.get("message")) and "dataset" not in row
    assert not engine.requests


def test_analytics_text_only_and_requires_access(analytics):
    client, remote, engine = analytics
    payload = {"message": "Как рассчитать прибыль?"}
    assert client.post(URL, json=payload).status_code == 401
    remote.records["connect_requests"][0]["status"] = "pending"
    assert client.post(URL, headers=auth(), json=payload).status_code == 403
    assert not remote.records["agent_runs"]
    remote.records["connect_requests"][0]["status"] = "approved"
    reply = client.post(URL, headers=auth(), json=payload)
    assert reply.status_code == 200 and reply.json()["execution"]["response"]
    assert remote.records["agent_runs"][0]["file_count"] == 0
    assert not engine.requests


def test_archived_placeholder_leaves_one_card_and_preserves_legacy_url_and_key(integration_environment):
    client, remote, engine = integration_environment
    legacy = remote.records["agents"][0]
    legacy.update(slug=LEGACY_SLUG, engine_slug=LEGACY_SLUG, name="Бизнес-аналитик")
    created = client.post("/api/integrations", headers=auth(),
        json={"agent_slug": LEGACY_SLUG, "name": "Существующее подключение"})
    assert created.status_code == 201, created.text
    headers = {"Authorization": "Bearer " + created.json()["api_key"]}
    authored_id = "40466f5f-1e54-4b52-bf63-5f280b79933a"
    authored = card(id=authored_id, slug=SLUG, name="Бизнес-аналитик", engine_slug=SLUG,
        description="Карточка разработчика с описанием анализа CSV и TSV.")
    legacy["status"] = "archived"
    remote.records["agents"].append(authored)
    remote.records["connect_requests"][0]["agent_id"] = authored_id
    remote.keys[0]["agent_id"] = authored_id

    assert [row["id"] for row in client.get("/api/agents").json()["items"]] == [authored_id]
    assert client.get(f"/api/agents/{LEGACY_SLUG}").json()["id"] == authored_id
    reply = client.post(f"/api/agents/{LEGACY_SLUG}/run", headers=auth(), json={"message": "Как рассчитать прибыль?"})
    assert reply.status_code == 200 and reply.json()["execution"]["agent"] == SLUG
    reply = client.post(f"/api/agents/{LEGACY_SLUG}/v1/chat/completions", headers=headers,
        json={"model": f"keme/{LEGACY_SLUG}", "messages": [{"role": "user", "content": "Как рассчитать прибыль?"}]})
    assert reply.status_code == 200 and reply.json()["model"] == f"keme/{LEGACY_SLUG}"
    assert remote.records["agent_runs"][-1]["agent_id"] == authored_id
    assert not engine.requests


@pytest.mark.parametrize("data, status, code", [
    ('revenue,cost\n100,broken\n', 422, "dataset_number"),
    ('revenue,cost\n100,40,10\n', 422, "dataset_width"),
    ('revenue,cost\n' + '100,40\n' * 5001, 422, "dataset_rows"),
    ('revenue,cost\n' + '1' * (128 * 1024), 413, "dataset_size"),
    ('revenue,cost\n\ud800,40\n', 422, "dataset_format"),
], ids=["number", "width", "row-limit", "size-limit", "invalid-utf8"])
def test_invalid_dataset_explains_failure_and_audits(analytics, data, status, code):
    client, remote, engine = analytics
    reply = client.post(URL, headers={**auth(), "Content-Type": "application/json"}, content=json.dumps({
        "message": "Посчитай прибыль", "language": "ru", "dataset": {"filename": "bad.csv", "text": data}}))
    assert reply.status_code == status, reply.text
    assert reply.json()["error"]["code"] == code
    assert reply.json()["error"]["message"]
    assert remote.records["agent_runs"][0]["status"] == "rejected"
    assert not engine.requests


def test_deployment_smoke_rejects_wrong_revision_and_activates_existing_card_twice():
    class Catalog:
        card = {"id": "original", "engine_slug": None, "status": "coming_soon"}
        writes = []

        async def request(self, method, path, *, params, body=None):
            assert path == "/rest/v1/agents" and params["slug"] == f"eq.{SLUG}"
            if method == "PATCH":
                assert params["id"] == "eq.original"
                if self.card["engine_slug"] is None:
                    assert params["engine_slug"] == "is.null"
                else:
                    assert params["engine_slug"] == f"eq.{SLUG}"
                self.card.update(body)
                self.writes.append(body)
            return [dict(self.card)]

    async def exercise():
        store = Catalog()
        def probe(request):
            assert request.url.path == "/api/health/business-analytics"
            return httpx.Response(200, json={"status": "ok", "agent": SLUG, "revision": "tested"})
        async with httpx.AsyncClient(transport=httpx.MockTransport(probe)) as client:
            with pytest.raises(RuntimeError, match="deployed revision"):
                await activate_healthy(client, "https://staging.example", "wrong", store)
            assert not store.writes and store.card["status"] == "coming_soon"
            await activate_healthy(client, "https://staging.example", "tested", store)
            await activate_healthy(client, "https://staging.example", "tested", store)
        assert store.card["id"] == "original" and store.card["status"] == "published"
        assert store.card["auto_connect"] is True
        assert sum("engine_slug" in write for write in store.writes) == 1

    asyncio.run(exercise())
