from __future__ import annotations

from pathlib import Path

from flash_sale_qa.storage import OrderStore, SessionStore


async def test_session_round_trip(tmp_path: Path) -> None:
    store = SessionStore(str(tmp_path / "sessions"))
    await store.save("qa/user", "token-1", 3600)
    value = await store.load("qa/user")
    assert value is not None
    assert value["access_token"] == "token-1"
    await store.invalidate("qa/user")
    assert await store.load("qa/user") is None


async def test_order_limit_count(tmp_path: Path) -> None:
    store = OrderStore(str(tmp_path / "orders.db"))
    await store.initialize()
    await store.record(
        account_name="qa-1",
        product_id="sku-1",
        order_id="o-1",
        status="simulated",
        dry_run=True,
        details={},
    )
    await store.record(
        account_name="qa-1",
        product_id="sku-1",
        order_id=None,
        status="failed",
        dry_run=True,
        details={},
    )
    assert await store.count_successes_24h("qa-1") == 1
