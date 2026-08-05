from __future__ import annotations

from aiohttp.test_utils import TestClient, TestServer

from flash_sale_qa.mock_store import create_app


async def test_complete_mock_checkout_flow() -> None:
    async with TestClient(TestServer(create_app())) as client:
        login = await client.post(
            "/api/test/login",
            json={"phone": "9000000001", "test_account": True},
        )
        assert login.status == 200
        token = (await login.json())["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        product = await client.get("/api/test/products/sku-1")
        assert product.status == 200

        cart = await client.post(
            "/api/test/cart/items",
            headers=headers,
            json={"product_id": "sku-1", "quantity": 1, "size": "M"},
        )
        assert cart.status == 201

        address = await client.post(
            "/api/test/checkout/address",
            headers=headers,
            json={"address": {"line1": "Test"}},
        )
        assert address.status == 201

        coupon = await client.post(
            "/api/test/checkout/coupon/apply",
            headers=headers,
            json={"code": "SAVE100"},
        )
        assert coupon.status == 200

        payment = await client.post(
            "/api/test/checkout/payment",
            headers=headers,
            json={"method": "TEST_COD"},
        )
        assert payment.status == 200

        order = await client.post(
            "/api/test/orders",
            headers=headers,
            json={"dry_run": True, "idempotency_key": "test-key"},
        )
        assert order.status == 201
        payload = await order.json()
        assert payload["status"] == "simulated"
