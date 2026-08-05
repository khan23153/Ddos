from __future__ import annotations

import dataclasses
import hashlib
import logging
import time
import uuid
from typing import Any

from .client import StagingClient
from .config import Account, Config, ProductRule
from .errors import ApiError, StopAccount
from .logging_utils import log_event
from .retry import with_retry
from .storage import OrderStore, SessionStore


class AccountWorkflow:
    def __init__(
        self,
        config: Config,
        client: StagingClient,
        sessions: SessionStore,
        orders: OrderStore,
        logger: logging.Logger,
    ) -> None:
        self.config = config
        self.client = client
        self.sessions = sessions
        self.orders = orders
        self.logger = logger

    async def login(self, account: Account) -> str:
        result = await with_retry(
            lambda: self.client.request(
                "POST",
                "/api/test/login",
                json_body={"phone": account.phone, "test_account": True},
                expected={200, 201},
            ),
            logger=self.logger,
            event="login_retry",
            account=account.name,
        )
        token = str(result.get("access_token", ""))
        if not token:
            raise ApiError("Login response did not contain access_token")
        await self.sessions.save(account.name, token, int(result.get("expires_in", 3600)))
        log_event(
            self.logger,
            logging.INFO,
            "login_success",
            "Test account authenticated",
            account=account.name,
        )
        return token

    async def token_for(self, account: Account) -> str:
        stored = await self.sessions.load(account.name)
        if stored:
            token = str(stored["access_token"])
            try:
                await self.client.request("GET", "/api/test/cart", token=token)
                return token
            except ApiError as error:
                if error.status not in {401, 403}:
                    raise
                await self.sessions.invalidate(account.name)
        return await self.login(account)

    async def authenticated(
        self,
        account: Account,
        token: str,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        expected: set[int] | None = None,
    ) -> tuple[dict[str, Any], str]:
        try:
            return (
                await self.client.request(
                    method,
                    path,
                    token=token,
                    json_body=json_body,
                    expected=expected,
                ),
                token,
            )
        except ApiError as error:
            if error.status not in {401, 403}:
                raise
            await self.sessions.invalidate(account.name)
            token = await self.login(account)
            result = await self.client.request(
                method,
                path,
                token=token,
                json_body=json_body,
                expected=expected,
            )
            return result, token

    async def ensure_address(self, account: Account, token: str) -> str:
        checkout, token = await self.authenticated(
            account,
            token,
            "GET",
            "/api/test/checkout",
        )
        addresses = checkout.get("saved_addresses", [])
        if isinstance(addresses, list) and addresses:
            return token
        _, token = await self.authenticated(
            account,
            token,
            "POST",
            "/api/test/checkout/address",
            json_body={"address": dataclasses.asdict(account.address)},
            expected={200, 201},
        )
        return token

    async def select_best_coupon(self, account: Account, token: str) -> tuple[str | None, str]:
        best_code: str | None = None
        best_reduction = 0.0
        for code in self.config.coupons:
            preview, token = await self.authenticated(
                account,
                token,
                "POST",
                "/api/test/checkout/coupon/preview",
                json_body={"code": code},
                expected={200, 422},
            )
            if preview.get("valid") is True:
                reduction = float(preview.get("reduction", 0))
                if reduction > best_reduction:
                    best_reduction = reduction
                    best_code = code
        if best_code:
            _, token = await self.authenticated(
                account,
                token,
                "POST",
                "/api/test/checkout/coupon/apply",
                json_body={"code": best_code},
            )
        return best_code, token

    async def execute_order(self, account: Account, product: ProductRule) -> None:
        started = time.monotonic()
        used = await self.orders.count_successes_24h(account.name)
        if used >= self.config.max_orders_per_account:
            raise StopAccount("Rolling 24-hour account order limit reached")

        try:
            token = await self.token_for(account)
            product_data, token = await self.authenticated(
                account,
                token,
                "GET",
                product.path,
            )
            if product_data.get("in_stock") is not True:
                raise StopAccount("Product is out of stock")

            sizes = product_data.get("sizes", [])
            chosen_size = product.preferred_size
            if chosen_size and isinstance(sizes, list) and sizes and chosen_size not in sizes:
                chosen_size = str(sizes[0])

            _, token = await self.authenticated(
                account,
                token,
                "POST",
                "/api/test/cart/items",
                json_body={
                    "product_id": product.id,
                    "quantity": product.quantity,
                    "size": chosen_size,
                },
                expected={200, 201},
            )
            token = await self.ensure_address(account, token)
            coupon, token = await self.select_best_coupon(account, token)
            _, token = await self.authenticated(
                account,
                token,
                "POST",
                "/api/test/checkout/payment",
                json_body={"method": "TEST_COD"},
            )

            source = f"{account.name}:{product.id}:{time.time_ns()}:{uuid.uuid4()}"
            idempotency_key = hashlib.sha256(source.encode()).hexdigest()
            result, _ = await self.authenticated(
                account,
                token,
                "POST",
                "/api/test/orders",
                json_body={
                    "confirm": True,
                    "dry_run": self.config.dry_run,
                    "idempotency_key": idempotency_key,
                },
                expected={200, 201, 202},
            )
            order_id = str(result.get("order_id") or f"sim-{uuid.uuid4().hex[:12]}")
            status = "simulated" if self.config.dry_run else str(result.get("status", "placed"))
            await self.orders.record(
                account_name=account.name,
                product_id=product.id,
                order_id=order_id,
                status=status,
                dry_run=self.config.dry_run,
                details={
                    "coupon": coupon,
                    "quantity": product.quantity,
                    "size": chosen_size,
                    "response": result,
                },
            )
            log_event(
                self.logger,
                logging.INFO,
                "order_success",
                f"Order workflow completed with status {status}",
                account=account.name,
                product=product.id,
                order_id=order_id,
                status=status,
                duration_ms=int((time.monotonic() - started) * 1000),
            )
        except StopAccount as error:
            log_event(
                self.logger,
                logging.INFO,
                "account_skipped",
                str(error),
                account=account.name,
                product=product.id,
            )
        except Exception as error:
            await self.orders.record(
                account_name=account.name,
                product_id=product.id,
                order_id=None,
                status="failed",
                dry_run=self.config.dry_run,
                details={"error": str(error), "error_type": type(error).__name__},
            )
            log_event(
                self.logger,
                logging.ERROR,
                "order_failure",
                str(error),
                account=account.name,
                product=product.id,
                error_type=type(error).__name__,
                duration_ms=int((time.monotonic() - started) * 1000),
            )
