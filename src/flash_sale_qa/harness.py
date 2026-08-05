from __future__ import annotations

import asyncio
import contextlib
import logging

from .client import StagingClient
from .config import Account, Config, ProductRule
from .logging_utils import log_event
from .notifier import TelegramNotifier
from .retry import with_retry
from .workflow import AccountWorkflow


class FlashSaleHarness:
    def __init__(
        self,
        config: Config,
        client: StagingClient,
        notifier: TelegramNotifier,
        workflow: AccountWorkflow,
        logger: logging.Logger,
        stop_event: asyncio.Event,
    ) -> None:
        self.config = config
        self.client = client
        self.notifier = notifier
        self.workflow = workflow
        self.logger = logger
        self.stop_event = stop_event
        self.semaphore = asyncio.Semaphore(config.max_concurrency)
        self.active_products: set[str] = set()
        self.active_lock = asyncio.Lock()
        self.blitz_tasks: set[asyncio.Task[None]] = set()

    def _track_blitz(self, task: asyncio.Task[None]) -> None:
        self.blitz_tasks.add(task)
        task.add_done_callback(self.blitz_tasks.discard)

    async def monitor_product(self, rule: ProductRule) -> None:
        while not self.stop_event.is_set():
            try:
                product = await with_retry(
                    lambda: self.client.request("GET", rule.path),
                    logger=self.logger,
                    event="monitor_retry",
                )
                price = float(product.get("price", float("inf")))
                discount = float(product.get("discount_percent", 0))
                in_stock = product.get("in_stock") is True
                triggered = in_stock and (
                    price <= rule.target_price or discount >= rule.target_discount
                )
                log_event(
                    self.logger,
                    logging.INFO,
                    "product_observation",
                    f"price={price:.2f} discount={discount:.1f} in_stock={in_stock}",
                    product=rule.id,
                    status="triggered" if triggered else "waiting",
                )
                if triggered:
                    async with self.active_lock:
                        if rule.id not in self.active_products:
                            self.active_products.add(rule.id)
                            task = asyncio.create_task(
                                self.trigger_blitz(rule, product),
                                name=f"blitz:{rule.id}",
                            )
                            self._track_blitz(task)
            except asyncio.CancelledError:
                raise
            except Exception as error:
                log_event(
                    self.logger,
                    logging.ERROR,
                    "monitor_failure",
                    str(error),
                    product=rule.id,
                    error_type=type(error).__name__,
                )

            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(
                    self.stop_event.wait(),
                    timeout=self.config.monitor_interval_seconds,
                )

    async def run_account(self, account: Account, rule: ProductRule) -> None:
        if self.stop_event.is_set():
            return
        async with self.semaphore:
            await self.workflow.execute_order(account, rule)

    async def trigger_blitz(self, rule: ProductRule, product: dict) -> None:
        try:
            await self.notifier.send_deal(
                name=str(product.get("name", rule.id)),
                price=float(product.get("price", 0)),
                discount=float(product.get("discount_percent", 0)),
                product_url=self.client.absolute_url(rule.path),
                image_url=str(product["image_url"]) if product.get("image_url") else None,
            )
            log_event(
                self.logger,
                logging.INFO,
                "blitz_started",
                f"Starting blitz for {len(self.config.accounts)} accounts",
                product=rule.id,
            )
            await asyncio.gather(
                *(self.run_account(account, rule) for account in self.config.accounts),
                return_exceptions=True,
            )
            log_event(
                self.logger,
                logging.INFO,
                "blitz_finished",
                "Blitz completed",
                product=rule.id,
            )
        finally:
            async with self.active_lock:
                self.active_products.discard(rule.id)

    async def run(self) -> None:
        monitors = [
            asyncio.create_task(self.monitor_product(product), name=f"monitor:{product.id}")
            for product in self.config.products
        ]
        log_event(
            self.logger,
            logging.INFO,
            "harness_started",
            f"products={len(monitors)} dry_run={self.config.dry_run}",
        )
        await self.stop_event.wait()
        for task in monitors:
            task.cancel()
        await asyncio.gather(*monitors, return_exceptions=True)

        pending = list(self.blitz_tasks)
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

        log_event(
            self.logger,
            logging.INFO,
            "harness_stopped",
            "Graceful shutdown completed",
        )
