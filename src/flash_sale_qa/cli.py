from __future__ import annotations

import argparse
import asyncio
import contextlib
import dataclasses
import json
import os
import signal
import sys
from datetime import UTC, datetime

import aiohttp

from .client import StagingClient
from .config import Config
from .harness import FlashSaleHarness
from .logging_utils import configure_logging, log_event
from .notifier import TelegramNotifier
from .rate_limit import SlidingWindowRateLimiter
from .storage import OrderStore, SessionStore
from .telegram_bot import TelegramCommandBot
from .workflow import AccountWorkflow


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Authorized staging-only flash-sale QA harness"
    )
    parser.add_argument("--config", default="config.json", help="JSON configuration path")
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Disable dry-run; requires QA_EXECUTION_CONFIRMED=YES",
    )
    parser.add_argument(
        "--run-seconds",
        type=float,
        default=0,
        help="Stop automatically after N seconds; zero means run until interrupted",
    )
    return parser.parse_args()


def install_signal_handlers(stop_event: asyncio.Event, logger) -> None:
    loop = asyncio.get_running_loop()

    def request_shutdown() -> None:
        if not stop_event.is_set():
            log_event(logger, 30, "shutdown_requested", "Shutdown signal received")
            stop_event.set()

    for signal_name in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(signal_name, request_shutdown)


async def stop_after(seconds: float, stop_event: asyncio.Event) -> None:
    await asyncio.sleep(seconds)
    stop_event.set()


async def async_main(args: argparse.Namespace) -> int:
    config = Config.load(args.config)
    if args.execute:
        if os.getenv("QA_EXECUTION_CONFIRMED") != "YES":
            raise RuntimeError("--execute requires QA_EXECUTION_CONFIRMED=YES")
        config = dataclasses.replace(config, dry_run=False)

    logger = configure_logging(config.log_dir)
    stop_event = asyncio.Event()
    install_signal_handlers(stop_event, logger)

    timeout = aiohttp.ClientTimeout(
        total=config.request_timeout_seconds,
        connect=min(10.0, config.request_timeout_seconds),
    )
    connector = aiohttp.TCPConnector(
        limit=max(config.max_concurrency * 2, 20),
        ttl_dns_cache=60,
        enable_cleanup_closed=True,
    )

    orders = OrderStore(config.database_path)
    await orders.initialize()
    sessions = SessionStore(config.session_dir)
    limiter = SlidingWindowRateLimiter(config.requests_per_second)

    async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
        client = StagingClient(config, session, limiter, logger)
        notifier = TelegramNotifier(config.telegram, session, logger)
        workflow = AccountWorkflow(config, client, sessions, orders, logger)
        harness = FlashSaleHarness(
            config,
            client,
            notifier,
            workflow,
            logger,
            stop_event,
        )
        telegram_bot = TelegramCommandBot(
            config,
            session,
            logger,
            stop_event,
            harness.trigger_product,
            harness.status_text,
        )

        timer = None
        if args.run_seconds > 0:
            timer = asyncio.create_task(stop_after(args.run_seconds, stop_event))
        bot_task = asyncio.create_task(
            telegram_bot.run(),
            name="telegram-command-bot",
        )
        try:
            await harness.run()
        finally:
            if timer:
                timer.cancel()
            bot_task.cancel()
            await asyncio.gather(
                *(task for task in (timer, bot_task) if task is not None),
                return_exceptions=True,
            )
    return 0


def main() -> int:
    args = parse_args()
    try:
        return asyncio.run(async_main(args))
    except KeyboardInterrupt:
        return 130
    except Exception as error:
        print(
            json.dumps(
                {
                    "timestamp": datetime.now(UTC).isoformat(),
                    "level": "CRITICAL",
                    "event": "startup_failure",
                    "message": str(error),
                    "error_type": type(error).__name__,
                }
            ),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
