"""PayLink test payments. These routes never grant access or settle funds."""
import hashlib
import hmac
import os
from typing import Annotated
from urllib.parse import urlsplit
from uuid import uuid4

from dotenv import dotenv_values
import httpx
from fastapi import APIRouter, Request
from pydantic import BaseModel, StringConstraints

from .errors import APIError
from .marketplace import Business
from .models import InputModel

router = APIRouter(prefix="/payments", tags=["Test payments"])
CHECKOUT = "https://checkout.paylink.kz/ctp/api/checkouts"
AMOUNT = 100_000  # 1,000 KZT, test price only
CURRENCY = "KZT"
RETURN_PATH = "/account/?view=payments"


class CheckoutStatus(InputModel):
    token: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{1,200}$")]
    order: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{32}$")]
    signature: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


def credentials(request: Request):
    return request.app.state.paylink_test


def load_paylink_test(root):
    values = {**dotenv_values(root / ".env"), **os.environ}
    shop = values.get("PAYLINK_TEST_SHOP_ID")
    secret = values.get("PAYLINK_TEST_SECRET_KEY")
    return (shop, secret) if shop and shop.isascii() and shop.isdecimal() and 1 <= len(shop) <= 12 and int(shop) > 0 and secret else None


def signature(secret, user, order, token):
    return hmac.new(secret.encode(), f"keme:paylink:test:{user.user_id}:{order}:{token}".encode(),
                    hashlib.sha256).hexdigest()


async def paylink(request, method, url, auth, **kwargs):
    try:
        response = await request.app.state.paylink_http.request(
            method, url, auth=auth, headers={"Accept": "application/json", "X-API-Version": "2"}, **kwargs)
        response.raise_for_status()
        checkout = response.json()["checkout"]
        if not isinstance(checkout, dict):
            raise ValueError
        return checkout
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        raise APIError(502, "test_checkout_unavailable", "Не удалось связаться с тестовой оплатой PayLink.") from None


@router.get("/preview")
async def preview(user: Business, request: Request):
    return {"mode": "paylink_test" if credentials(request) else "simulation", "amount": AMOUNT, "currency": CURRENCY}


@router.post("/checkout", status_code=201)
async def checkout(user: Business, request: Request):
    auth = credentials(request)
    if not auth:
        raise APIError(503, "test_checkout_not_configured", "Тестовый магазин PayLink ещё не подключён.")
    request.app.state.auth_limiter.check(f"test_checkout:{user.user_id}")
    order = uuid4().hex
    origin = request.headers.get("origin", str(request.base_url).rstrip("/"))
    if origin not in request.app.state.gateway.settings.oauth_redirect_origins:
        raise APIError(422, "invalid_return_origin", "Откройте оплату на официальном сайте Keme AI.")
    return_url = origin + RETURN_PATH
    data = await paylink(request, "POST", CHECKOUT, auth, json={"checkout": {
        "test": True, "transaction_type": "payment",
        "order": {"tracking_id": order, "amount": AMOUNT, "currency": CURRENCY, "description": "Keme AI test checkout"},
        "settings": {"return_url": return_url, "fail_url": return_url, "cancel_url": return_url, "language": "ru",
                     "save_card_toggle": {"display": False}},
    }})
    token, redirect = data.get("token"), data.get("redirect_url")
    try:
        ticket = CheckoutStatus(token=token, order=order, signature=signature(auth[1], user, order, token))
        target = urlsplit(redirect)
        if target.scheme != "https" or target.netloc != "checkout.paylink.kz" or target.path != "/v2/checkout":
            raise ValueError
        if data.get("test") is False:
            raise ValueError
    except (ValueError, TypeError, AttributeError):
        raise APIError(502, "invalid_test_checkout", "PayLink вернул неожиданный адрес оплаты.") from None
    return {**ticket.model_dump(), "redirect_url": redirect}


@router.post("/status")
async def checkout_status(body: CheckoutStatus, user: Business, request: Request):
    auth = credentials(request)
    if not auth or not hmac.compare_digest(body.signature, signature(auth[1], user, body.order, body.token)):
        raise APIError(404, "test_checkout_not_found", "Тестовый заказ не найден.")
    data = await paylink(request, "GET", f"{CHECKOUT}/{body.token}", auth)
    order = data.get("order")
    if (data.get("test") is not True or data.get("token") != body.token or str(data.get("shop_id")) != str(int(auth[0]))
        or not isinstance(order, dict) or order.get("tracking_id") != body.order
        or order.get("amount") != AMOUNT or order.get("currency") != CURRENCY):
        raise APIError(502, "invalid_test_checkout", "PayLink не подтвердил параметры тестового заказа.")
    gateway = data.get("gateway_response")
    payment = gateway.get("payment") if isinstance(gateway, dict) else None
    if (data.get("status") == "successful" and isinstance(payment, dict) and payment.get("status") == "successful"
        and payment.get("amount") == AMOUNT and payment.get("currency") == CURRENCY):
        return {"status": "successful"}
    return {"status": "unsuccessful" if data.get("finished") or data.get("expired") else "pending"}
