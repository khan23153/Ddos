from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

import aiohttp

from .config import Config
from .logging_utils import log_event

TriggerCallback = Callable[[str], Awaitable[str]]
StatusCallback = Callable[[], str]


class TelegramCommandBot:
    """Restricted Telegram long-polling controller for the staging QA harness."""

    def __init__(
        self,
        config: Config,
        session: aiohttp.ClientSession,
        logger: logging.Logger,
        stop_event: asyncio.Event,
        trigger: TriggerCallback,
        status: StatusCallback,
    ) -> None:
        self.bot_token = config.telegram.bot_token
        self.chat_id = str(config.telegram.chat_id)
        self.enabled = config.telegram.command_bot_enabled
        self.poll_timeout = config.telegram.poll_timeout_seconds
        self.session = session
        self.logger = logger
        self.stop_event = stop_event
        self.trigger = trigger
        self.status = status
        self.products = {product.id: product for product in config.products}
        self.offset = 0

    @property
    def configured(self) -> bool:
        return bool(self.enabled and self.bot_token and self.chat_id)

    async def _api(self, method: str, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"https://api.telegram.org/bot{self.bot_token}/{method}"
        async with self.session.post(url, json=payload) as response:
            body = await response.json(content_type=None)
            if response.status >= 300 or body.get("ok") is not True:
                raise RuntimeError(f"Telegram {method} failed: {body}")
            return body

    async def send(self, text: str) -> None:
        await self._api(
            "sendMessage",
            {
                "chat_id": self.chat_id,
                "text": text,
                "disable_web_page_preview": True,
            },
        )

    async def _updates(self) -> list[dict[str, Any]]:
        body = await self._api(
            "getUpdates",
            {
                "offset": self.offset,
                "timeout": self.poll_timeout,
                "allowed_updates": ["message"],
            },
        )
        result = body.get("result", [])
        return result if isinstance(result, list) else []

    def _help(self) -> str:
        return (
            "Flash Sale QA Bot\n"
            "/status - harness state\n"
            "/products - configured staging products\n"
            "/trigger <product_id> - start a staging blitz\n"
            "/stop - gracefully stop the harness\n"
            "/help - show commands"
        )

    async def _handle(self, update: dict[str, Any]) -> None:
        self.offset = max(self.offset, int(update.get("update_id", 0)) + 1)
        message = update.get("message")
        if not isinstance(message, dict):
            return

        chat = message.get("chat")
        sender_chat_id = str(chat.get("id", "")) if isinstance(chat, dict) else ""
        if sender_chat_id != self.chat_id:
            log_event(
                self.logger,
                logging.WARNING,
                "telegram_unauthorized_command",
                "Ignored Telegram command from unauthorized chat",
                status=sender_chat_id,
            )
            return

        text = str(message.get("text", "")).strip()
        if not text.startswith("/"):
            return

        command, *arguments = text.split()
        command = command.split("@", 1)[0].lower()

        if command in {"/start", "/help"}:
            await self.send(self._help())
        elif command == "/status":
            await self.send(self.status())
        elif command == "/products":
            lines = ["Configured staging products:"]
            for product in self.products.values():
                lines.append(
                    f"- {product.id}: price≤₹{product.target_price:.2f} "
                    f"or discount≥{product.target_discount:.1f}%"
                )
            await self.send("\n".join(lines))
        elif command == "/trigger":
            if not arguments:
                await self.send("Usage: /trigger <product_id>")
                return
            result = await self.trigger(arguments[0])
            await self.send(result)
        elif command == "/stop":
            self.stop_event.set()
            await self.send("Graceful shutdown requested.")
        else:
            await self.send(self._help())

    async def run(self) -> None:
        if not self.configured:
            return

        log_event(
            self.logger,
            logging.INFO,
            "telegram_command_bot_started",
            "Telegram command bot started",
        )
        await self.send("Flash Sale QA Bot online. Use /help for commands.")

        while not self.stop_event.is_set():
            try:
                for update in await self._updates():
                    await self._handle(update)
            except asyncio.CancelledError:
                raise
            except Exception as error:
                log_event(
                    self.logger,
                    logging.WARNING,
                    "telegram_command_bot_error",
                    str(error),
                    error_type=type(error).__name__,
                )
                await asyncio.sleep(2)

        log_event(
            self.logger,
            logging.INFO,
            "telegram_command_bot_stopped",
            "Telegram command bot stopped",
        )
