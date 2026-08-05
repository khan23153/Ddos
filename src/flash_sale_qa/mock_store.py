from __future__ import annotations

import argparse
import secrets
import time
import uuid
from collections import defaultdict
from typing import Any

from aiohttp import web

PRODUCTS: dict[str, dict[str, Any]] = {
    "sku-1": {
        "id": "sku-1",
        "name": "Staging Flash Product",
        "price": 899.0,
        "discount_percent": 55.0,
        "in_stock": True,
        "image_url": "https://picsum.photos/seed/flash-sale-qa/640/640",
        "sizes": ["S", "M", "L"],
    }
}
COUPONS = {"EXTRA20": 20.0, "FLASH50": 50.0, "SAVE100": 100.0}


class MockState:
    def __init__(self) -> None:
        self.tokens: dict[str, str] = {}
        self.carts: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self.addresses: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self.applied_coupon: dict[str, str] = {}
        self.payment_method: dict[str, str] = {}
        self.idempotency: dict[str, dict[str, Any]] = {}

    def account_for(self, request: web.Request) -> str:
        header = request.headers.get("Authorization", "")
        if not header.startswith("Bearer "):
            raise web.HTTPUnauthorized(text="missing bearer token")
        token = header.removeprefix("Bearer ").strip()
        account = self.tokens.get(token)
        if not account:
            raise web.HTTPUnauthorized(text="invalid token")
        return account


STATE_KEY = web.AppKey("state", MockState)


async def health(_: web.Request) -> web.Response:
    return web.json_response({"status": "ok", "service": "flash-sale-mock-store"})


async def login(request: web.Request) -> web.Response:
    state: MockState = request.app[STATE_KEY]
    body = await request.json()
    if body.get("test_account") is not True:
        raise web.HTTPForbidden(text="test_account=true is required")
    phone = str(body.get("phone", "")).strip()
    if not phone:
        raise web.HTTPBadRequest(text="phone is required")
    token = secrets.token_urlsafe(32)
    state.tokens[token] = phone
    return web.json_response({"access_token": token, "expires_in": 3600})


async def get_cart(request: web.Request) -> web.Response:
    state: MockState = request.app[STATE_KEY]
    account = state.account_for(request)
    return web.json_response({"items": state.carts[account]})


async def get_product(request: web.Request) -> web.Response:
    product_id = request.match_info["product_id"]
    product = PRODUCTS.get(product_id)
    if not product:
        raise web.HTTPNotFound(text="unknown product")
    return web.json_response(product)


async def add_cart_item(request: web.Request) -> web.Response:
    state: MockState = request.app[STATE_KEY]
    account = state.account_for(request)
    body = await request.json()
    product_id = str(body.get("product_id", ""))
    product = PRODUCTS.get(product_id)
    if not product or product.get("in_stock") is not True:
        raise web.HTTPConflict(text="product unavailable")
    quantity = int(body.get("quantity", 1))
    if not 1 <= quantity <= 10:
        raise web.HTTPBadRequest(text="invalid quantity")
    item = {
        "product_id": product_id,
        "quantity": quantity,
        "size": body.get("size"),
        "unit_price": product["price"],
    }
    state.carts[account].append(item)
    return web.json_response({"added": True, "item": item}, status=201)


def calculate_checkout(state: MockState, account: str) -> dict[str, Any]:
    subtotal = sum(item["unit_price"] * item["quantity"] for item in state.carts[account])
    code = state.applied_coupon.get(account)
    reduction = min(subtotal, COUPONS.get(code or "", 0.0))
    return {
        "subtotal": subtotal,
        "discount": reduction,
        "total": max(0.0, subtotal - reduction),
        "saved_addresses": state.addresses[account],
        "coupon": code,
    }


async def get_checkout(request: web.Request) -> web.Response:
    state: MockState = request.app[STATE_KEY]
    account = state.account_for(request)
    return web.json_response(calculate_checkout(state, account))


async def save_address(request: web.Request) -> web.Response:
    state: MockState = request.app[STATE_KEY]
    account = state.account_for(request)
    body = await request.json()
    address = body.get("address")
    if not isinstance(address, dict):
        raise web.HTTPBadRequest(text="address object is required")
    state.addresses[account] = [address]
    return web.json_response({"saved": True, "address": address}, status=201)


async def preview_coupon(request: web.Request) -> web.Response:
    state: MockState = request.app[STATE_KEY]
    account = state.account_for(request)
    body = await request.json()
    code = str(body.get("code", "")).upper()
    checkout = calculate_checkout(state, account)
    reduction = min(checkout["subtotal"], COUPONS.get(code, 0.0))
    if code not in COUPONS:
        return web.json_response(
            {"valid": False, "reduction": 0, "total": checkout["subtotal"]},
            status=422,
        )
    return web.json_response(
        {"valid": True, "reduction": reduction, "total": checkout["subtotal"] - reduction}
    )


async def apply_coupon(request: web.Request) -> web.Response:
    state: MockState = request.app[STATE_KEY]
    account = state.account_for(request)
    code = str((await request.json()).get("code", "")).upper()
    if code not in COUPONS:
        raise web.HTTPUnprocessableEntity(text="invalid coupon")
    state.applied_coupon[account] = code
    return web.json_response({"applied": True, "code": code})


async def set_payment(request: web.Request) -> web.Response:
    state: MockState = request.app[STATE_KEY]
    account = state.account_for(request)
    method = str((await request.json()).get("method", ""))
    if method != "TEST_COD":
        raise web.HTTPUnprocessableEntity(text="only TEST_COD is supported")
    state.payment_method[account] = method
    return web.json_response({"selected": method})


async def create_order(request: web.Request) -> web.Response:
    state: MockState = request.app[STATE_KEY]
    account = state.account_for(request)
    body = await request.json()
    key = str(body.get("idempotency_key", ""))
    if not key:
        raise web.HTTPBadRequest(text="idempotency_key is required")
    if key in state.idempotency:
        return web.json_response(state.idempotency[key])
    if not state.carts[account]:
        raise web.HTTPConflict(text="cart is empty")
    if not state.addresses[account]:
        raise web.HTTPConflict(text="address is missing")
    if state.payment_method.get(account) != "TEST_COD":
        raise web.HTTPConflict(text="payment method is missing")

    dry_run = bool(body.get("dry_run", True))
    result = {
        "order_id": f"qa-{uuid.uuid4().hex[:12]}",
        "status": "simulated" if dry_run else "placed",
        "created_at": int(time.time()),
        "checkout": calculate_checkout(state, account),
    }
    state.idempotency[key] = result
    state.carts[account] = []
    return web.json_response(result, status=201)


def create_app() -> web.Application:
    app = web.Application(client_max_size=1024 * 1024)
    app[STATE_KEY] = MockState()
    app.add_routes(
        [
            web.get("/health", health),
            web.post("/api/test/login", login),
            web.get("/api/test/cart", get_cart),
            web.get("/api/test/products/{product_id}", get_product),
            web.post("/api/test/cart/items", add_cart_item),
            web.get("/api/test/checkout", get_checkout),
            web.post("/api/test/checkout/address", save_address),
            web.post("/api/test/checkout/coupon/preview", preview_coupon),
            web.post("/api/test/checkout/coupon/apply", apply_coupon),
            web.post("/api/test/checkout/payment", set_payment),
            web.post("/api/test/orders", create_order),
        ]
    )
    return app


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Local mock store for flash-sale QA")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    web.run_app(create_app(), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
