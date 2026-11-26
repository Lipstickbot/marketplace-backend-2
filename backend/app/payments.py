"""Hosted card checkout, with access granted only after server-side verification."""
import hashlib
import hmac
import re
from urllib.parse import parse_qs, urlsplit
from uuid import UUID

import httpx
from fastapi import APIRouter, Request, Response
from pydantic import Field

from .errors import APIError
from .execution import Store
from .marketplace import Business, Client, one
from .marketplace_models import Agent
from .models import InputModel

router = APIRouter(prefix="/payments", tags=["Payments"])
CHECKOUT = "https://checkout.paylink.kz/ctp/api/checkouts"
ORDERS = "/rest/v1/agent_purchases"
CURRENCY = "KZT"


class Checkout(InputModel):
    agent_id: UUID
    amount: int = Field(ge=1, le=100_000_000, strict=True)


def credentials(request: Request) -> tuple[str, str]:
    settings = request.app.state.gateway.settings
    if settings.paylink_live_enabled and settings.paylink_live_shop_id and settings.paylink_live_secret_key:
        secret = settings.paylink_live_secret_key.get_secret_value()
        if secret:
            return str(settings.paylink_live_shop_id), secret
    raise APIError(503, "checkout_not_configured", "Оплата картой пока недоступна.")


async def paylink(request, method, url, auth, **kwargs):
    try:
        response = await request.app.state.paylink_http.request(
            method, url, auth=auth, headers={"Accept": "application/json", "X-API-Version": "2"}, **kwargs)
        response.raise_for_status()
        data = response.json()["checkout"]
        if isinstance(data, dict):
            return data
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        pass
    raise APIError(502, "checkout_unavailable", "Не удалось связаться с PayLink.")


def payment_error():
    return APIError(502, "checkout_mismatch", "PayLink не подтвердил параметры заказа.")


def notification_signature(order_id, secret):
    return hmac.new(secret.encode(), f"keme:payment:{order_id}".encode(), hashlib.sha256).hexdigest()


async def reconcile(order, request, store, auth):
    if order["status"] != "pending" or not order["provider_token"]:
        return order["status"]
    data = await paylink(request, "GET", f'{CHECKOUT}/{order["provider_token"]}', auth)
    purchased = data.get("order")
    if (data.get("test") is not False or data.get("token") != order["provider_token"]
        or str(data.get("shop_id")) != auth[0] or data.get("transaction_type") != "payment"
        or not isinstance(purchased, dict) or purchased.get("tracking_id") != order["id"]
        or purchased.get("amount") != order["amount"] or purchased.get("currency") != CURRENCY):
        raise payment_error()
    if data.get("status") == "successful":
        gateway = data.get("gateway_response")
        payment = gateway.get("payment") if isinstance(gateway, dict) else None
        if (not isinstance(payment, dict) or payment.get("status") != "successful"
            or payment.get("amount") != order["amount"] or payment.get("currency") != CURRENCY
            or not isinstance(payment.get("uid"), str) or not 1 <= len(payment["uid"]) <= 100):
            raise payment_error()
        ok = await store.request("POST", "/rest/v1/rpc/complete_agent_purchase",
            body={"p_order": order["id"], "p_token": order["provider_token"], "p_payment_id": payment["uid"]})
        if ok is not True:
            raise payment_error()
        return "paid"
    if data.get("status") != "pending" and (data.get("finished") is True or data.get("expired") is True):
        rows = await store.request("PATCH", ORDERS, params={"id": f'eq.{order["id"]}', "status": "eq.pending"},
                                   body={"status": "failed", "checkout_url": None})
        if rows:
            return "failed"
        return "pending"  # A concurrent status check may have already completed it.
    return "pending"


@router.post("/checkout", status_code=201)
async def checkout(body: Checkout, user: Business, request: Request, store: Store, client: Client):
    auth = credentials(request)
    origin = request.headers.get("origin", str(request.base_url).rstrip("/"))
    if origin not in client.settings.oauth_redirect_origins:
        raise APIError(422, "invalid_return_origin", "Откройте оплату на официальном сайте Keme AI.")
    request.app.state.auth_limiter.check(f"checkout:{user.user_id}")
    agent = await one(client, "agents", Agent,
        filters={"id": f"eq.{body.agent_id}", "status": "eq.published"})
    result = await store.request("POST", "/rest/v1/rpc/reserve_agent_purchase",
        body={"p_company": str(user.company_id), "p_agent": str(agent.id), "p_amount": body.amount})
    if result.get("reason") == "already_connected":
        return {"status": "connected"}
    if result.get("reason") == "price_changed":
        raise APIError(409, "price_changed", "Цена изменилась. Обновите каталог перед оплатой.")
    order = result.get("order")
    if not order:
        raise APIError(409, "checkout_in_progress", "Попробуйте открыть оплату ещё раз.")
    order_id = order["id"]
    if not result["reserved"]:
        state = await reconcile(order, request, store, auth)
        if state == "failed":
            raise APIError(409, "retry_checkout", "Предыдущая оплата закрыта. Нажмите «Купить картой» ещё раз.")
        if state == "paid":
            return {"status": "connected"}
        if order["amount"] != body.amount:
            raise APIError(409, "checkout_price_changed", "Уже есть открытый заказ по прежней цене. Дождитесь его закрытия.")
        if not order["checkout_url"]:
            raise APIError(409, "checkout_in_progress", "Оплата создаётся. Попробуйте через несколько секунд.")
        return {"status": "pending", "redirect_url": order["checkout_url"]}

    return_url = f"{origin}/account/?view=payments&order={order_id}"
    settings = {"return_url": return_url, "success_url": return_url, "decline_url": return_url,
                "fail_url": return_url, "cancel_url": return_url, "language": "ru",
                "save_card_toggle": {"display": False}}
    callback = client.settings.paylink_notification_base
    if callback:
        signature = notification_signature(order_id, auth[1])
        settings["notification_url"] = f"{callback}/api/payments/notify/{order_id}/{signature}"
    try:
        data = await paylink(request, "POST", CHECKOUT, auth, json={"checkout": {
            "test": False, "transaction_type": "payment", "attempts": 1, "settings": settings,
            "payment_method": {"types": ["credit_card"]},
            "order": {"tracking_id": order_id, "amount": order["amount"], "currency": CURRENCY,
                      "description": f"Keme AI: {agent.name}"},
        }})
        provider_token, redirect = data.get("token"), data.get("redirect_url")
        try:
            target = urlsplit(redirect) if isinstance(redirect, str) else None
        except ValueError:
            raise payment_error() from None
        if (not isinstance(provider_token, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,200}", provider_token)
            or not target or target.scheme != "https" or target.netloc != "checkout.paylink.kz"
            or target.path != "/v2/checkout" or parse_qs(target.query).get("token") != [provider_token]
            or data.get("test") is True):
            raise payment_error()
        saved = await store.request("PATCH", ORDERS, params={"id": f"eq.{order_id}", "status": "eq.pending"},
                                    body={"provider_token": provider_token, "checkout_url": redirect})
        if not saved:
            raise payment_error()
    except APIError:
        # The link was never shared, so it cannot be used to pay this order.
        await store.request("PATCH", ORDERS,
            params={"id": f"eq.{order_id}", "status": "eq.pending", "provider_token": "is.null"},
            body={"status": "failed"})
        raise
    return {"status": "pending", "redirect_url": redirect}


@router.post("/status/{order_id}")
async def purchase_status(order_id: UUID, user: Business, request: Request, store: Store):
    auth = credentials(request)
    rows = await store.request("GET", ORDERS,
        params={"id": f"eq.{order_id}", "company_id": f"eq.{user.company_id}"})
    if not rows:
        raise APIError(404, "purchase_not_found", "Заказ не найден.")
    order = rows[0]
    result = order["status"]
    if result == "pending":
        request.app.state.auth_limiter.check(f"checkout_status:{user.user_id}")
        result = await reconcile(order, request, store, auth)
    return {"status": result, "agent_id": order["agent_id"]}


@router.post("/notify/{order_id}/{signature}", include_in_schema=False, status_code=204)
async def notification(order_id: UUID, signature: str, request: Request, store: Store):
    auth = credentials(request)
    if not re.fullmatch(r"[a-f0-9]{64}", signature) or not hmac.compare_digest(
            signature, notification_signature(order_id, auth[1])):
        raise APIError(404, "purchase_not_found", "Заказ не найден.")
    rows = await store.request("GET", ORDERS, params={"id": f"eq.{order_id}"})
    if rows:
        await reconcile(rows[0], request, store, auth)
    return Response(status_code=204)
