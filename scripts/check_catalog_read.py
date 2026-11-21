"""Read-only live check of the running Backend 2; creates no cloud records."""
import httpx


def main():
    with httpx.Client(base_url="http://127.0.0.1:8001", timeout=30, trust_env=False) as client:
        response = client.get("/health")
        assert response.status_code == 200 and response.json()["version"] == "0.4.0"
        assert client.get("/docs").status_code == 200
        page = client.get("/agents")
        assert page.status_code == 200
        assert {"items", "limit", "offset", "has_more"} <= page.json().keys()
        assert len(page.json()["items"]) == 12
        assert sum(row["status"] == "published" for row in page.json()["items"]) == 3
        engine = client.get("/engine/health")
        assert engine.status_code == 200 and engine.json()["llm_provider"] == "mock"
        search = client.get("/agents", params={"q": '100%_*,"x" (a.b)\\test', "category": 'support, (test)'})
        assert search.status_code == 200, f"Literal search failed: HTTP {search.status_code}"
        assert search.json()["items"] == []
        assert client.get("/agents/missing-agent-for-read-test").status_code == 404
        assert client.get("/agents", params={"status": "draft"}).status_code == 422
        for path in ["/connect-requests", "/agent-submissions", "/admin/agents", "/admin/connect-requests", "/admin/agent-submissions", "/files", "/runs"]:
            assert client.get(path).status_code == 401
        assert client.get("/admin/agents", headers={"Authorization": "Bearer invalid-test-token"}).status_code == 401
        print({"passed": 15, "api_version": "0.4.0", "cloud_records_created": 0})


if __name__ == "__main__":
    main()
