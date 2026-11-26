import json

import httpx
from fastapi.testclient import TestClient

from backend.app.config import Settings
from backend.app.main import create_app
from backend.tests.test_auth import FakeSupabase, auth


def test_paylink_checkout_is_test_only_and_confirms_provider_status():
    order = {}
    calls = []
    payment_is_test = True

    def provider(request):
        calls.append(request)
        assert request.url.host == "checkout.paylink.kz"
        assert request.headers["X-API-Version"] == "2"
        assert request.headers["authorization"].startswith("Basic ")
        if request.method == "POST":
            checkout = json.loads(request.content)["checkout"]
            assert checkout["test"] is True
            assert checkout["settings"]["return_url"] == "http://localhost:3000/account/?view=payments"
            order.update(checkout["order"])
            return httpx.Response(200, json={"checkout": {
                "token": "test-token", "redirect_url": "https://checkout.paylink.kz/v2/checkout?token=test-token",
            }})
        return httpx.Response(200, json={"checkout": {
            "token": "test-token", "shop_id": 12, "test": payment_is_test, "order": order,
            "status": "successful",
            "gateway_response": {"payment": {"status": "successful", "amount": 100000, "currency": "KZT"}},
        }})

    settings = Settings(supabase_url="https://project.supabase.co", supabase_publishable_key="sb_publishable_test")
    app = create_app(settings, transport=httpx.MockTransport(FakeSupabase()), paylink_transport=httpx.MockTransport(provider))
    app.state.paylink_test = None
    origin = {**auth(), "Origin": "http://localhost:3000"}
    with TestClient(app) as client:
        assert client.get("/api/payments/preview", headers=auth()).json()["mode"] == "simulation"
        assert client.post("/api/payments/checkout", headers=origin).status_code == 503
        app.state.paylink_test = ("12", "mock-paylink-secret")
        assert client.post("/api/payments/checkout").status_code == 401
        assert client.post("/api/payments/checkout", headers={**auth(), "Origin": "https://another.example"}).status_code == 422
        assert not calls
        assert client.get("/api/payments/preview", headers=auth()).json()["mode"] == "paylink_test"
        response = client.post("/api/payments/checkout", headers=origin)
        assert response.status_code == 201
        ticket = {name: value for name, value in response.json().items() if name != "redirect_url"}
        assert client.post("/api/payments/status", headers=auth(), json={**ticket, "token": "other"}).status_code == 404
        assert len(calls) == 1
        assert client.post("/api/payments/status", headers=auth(), json=ticket).json() == {"status": "successful"}
        payment_is_test = False
        assert client.post("/api/payments/status", headers=auth(), json=ticket).status_code == 502
