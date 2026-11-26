import json
from urllib.parse import urlsplit

import httpx
from fastapi.testclient import TestClient

from backend.app.config import Settings
from backend.app.main import create_app
from backend.tests.test_auth import A, auth
from backend.tests.test_marketplace import AGENT, MarketplaceFake, connection

ORDER = "80000000-0000-4000-8000-000000000001"
AMOUNT = 123_400
PAYLOAD = {"agent_id": AGENT, "amount": AMOUNT}
ORIGIN = {**auth(), "Origin": "http://localhost:3000"}


class PurchaseSupabase(MarketplaceFake):
    def __init__(self):
        super().__init__()
        self.records["agents"][0]["price_minor"] = AMOUNT
        self.records["connect_requests"] = []
        self.profiles["b"] = {"id": "00000000-0000-4000-8000-000000000009", "role": "business",
                              "display_name": "B", "company_name": "Business B"}
        self.sessions["b"] = True
        self.order = None
        self.grants = 0

    def __call__(self, request):
        path = request.url.path.removeprefix("/rest/v1/")
        if path not in {"agent_purchases", "rpc/reserve_agent_purchase", "rpc/complete_agent_purchase"}:
            return super().__call__(request)
        assert request.headers["apikey"] == "sb_secret_test"
        assert "authorization" not in request.headers
        if path == "rpc/reserve_agent_purchase":
            props = json.loads(request.content)
            assert props["p_company"] == A and props["p_agent"] == AGENT
            if props["p_amount"] != AMOUNT:
                return httpx.Response(200, json={"reason": "price_changed"})
            if self.grants:
                return httpx.Response(200, json={"reason": "already_connected"})
            fresh = self.order is None
            if fresh:
                self.order = {"id": ORDER, "company_id": A, "agent_id": AGENT, "provider_token": None,
                              "checkout_url": None, "status": "pending", "amount": AMOUNT}
            return httpx.Response(200, json={"order": self.order, "reserved": fresh})
        if path == "rpc/complete_agent_purchase":
            assert json.loads(request.content) == {"p_order": ORDER, "p_token": "hosted-token", "p_payment_id": "payment-id"}
            self.order["status"] = "paid"
            self.grants += 1
            self.records["connect_requests"] = [connection(status="approved")]
            return httpx.Response(200, json=True)
        if request.method == "PATCH":
            self.order.update(json.loads(request.content))
        if not self.order or request.url.params.get("id") != f"eq.{ORDER}":
            return httpx.Response(200, json=[])
        if request.url.params.get("company_id", f"eq.{A}") != f"eq.{A}":
            return httpx.Response(200, json=[])
        return httpx.Response(200, json=[self.order])


def test_checkout_is_disabled_by_default():
    settings = Settings(supabase_url="https://project.supabase.co", supabase_publishable_key="sb_publishable_test")
    with TestClient(create_app(settings, transport=httpx.MockTransport(PurchaseSupabase()))) as client:
        assert client.post("/api/payments/checkout", headers=ORIGIN, json=PAYLOAD).status_code == 503
        assert client.post("/api/payments/checkout", json=PAYLOAD).status_code == 401


def test_checkout_grants_access_once_only_after_verified_charge():
    remote, order, provider_posts = PurchaseSupabase(), {}, []
    provider_state = {"test": False, "state": "pending", "amount": AMOUNT}

    def provider(request):
        assert request.url.host == "checkout.paylink.kz"
        assert request.headers["X-API-Version"] == "2"
        assert request.headers["authorization"].startswith("Basic ")
        if request.method == "POST":
            params = json.loads(request.content)["checkout"]
            assert params["test"] is False and params["transaction_type"] == "payment"
            assert params["payment_method"]["types"] == ["credit_card"]
            assert params["settings"]["return_url"] == f"http://localhost:3000/account/?view=payments&order={ORDER}"
            provider_posts.append(params)
            order.update(params["order"])
            assert order["amount"] == AMOUNT and order["currency"] == "KZT"
            return httpx.Response(200, json={"checkout": {"token": "hosted-token",
                "redirect_url": "https://checkout.paylink.kz/v2/checkout?token=hosted-token"}})
        return httpx.Response(200, json={"checkout": {
            "token": "hosted-token", "shop_id": 12, "transaction_type": "payment",
            "test": provider_state["test"], "order": order, "status": provider_state["state"],
            "gateway_response": {"payment": {"status": "successful", "uid": "payment-id",
                                             "amount": provider_state["amount"], "currency": "KZT"}},
        }})

    settings = Settings(supabase_url="https://project.supabase.co", supabase_publishable_key="sb_publishable_test",
                        supabase_secret_key="sb_secret_test", paylink_live_enabled=True, paylink_live_shop_id=12,
                        paylink_live_secret_key="mock-paylink-secret", paylink_notification_base="https://app.example")
    app = create_app(settings, transport=httpx.MockTransport(remote), paylink_transport=httpx.MockTransport(provider))
    with TestClient(app) as client:
        assert client.post("/api/connect-requests", headers=auth(), json={"agent_id": AGENT}).status_code == 402
        assert client.post("/api/payments/checkout", headers={**ORIGIN, "Origin": "https://another.example"}, json=PAYLOAD).status_code == 422
        assert client.post("/api/payments/checkout", headers=ORIGIN, json={**PAYLOAD, "amount": 1}).status_code == 409
        assert not provider_posts
        checkout = client.post("/api/payments/checkout", headers=ORIGIN, json=PAYLOAD)
        assert checkout.status_code == 201, checkout.text
        assert client.post("/api/payments/checkout", headers=ORIGIN, json=PAYLOAD).json() == checkout.json()
        assert len(provider_posts) == 1
        status = f"/api/payments/status/{ORDER}"
        assert client.post(status, headers=auth("b")).status_code == 404
        assert client.post(status, headers=auth()).json()["status"] == "pending"
        provider_state.update(test=True, state="successful")
        assert client.post(status, headers=auth()).status_code == 502
        provider_state.update(test=False, amount=1)
        assert client.post(status, headers=auth()).status_code == 502
        assert remote.grants == 0
        assert client.post(f"/api/payments/notify/{ORDER}/{'0' * 64}").status_code == 404
        provider_state.update(amount=AMOUNT)
        notify = urlsplit(provider_posts[0]["settings"]["notification_url"]).path
        assert client.post(notify, json={"ignored": "untrusted notification"}).status_code == 204
        assert client.post(status, headers=auth()).json() == {"status": "paid", "agent_id": AGENT}
        assert client.post(notify).status_code == 204
        assert remote.grants == 1
        assert client.get("/api/connect-requests", headers=auth()).json()["items"][0]["status"] == "approved"
