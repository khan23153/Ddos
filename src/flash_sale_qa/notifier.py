from __future__ import annotations

import logging
import os

import aiohttp

from .config import TelegramConfig
from .logging_utils import log_event


class TelegramNotifier:
    def __init__(
        self,
        config: TelegramConfig,
        session: aiohttp.ClientSession,
        logger: logging.Logger,
    ) -> None:
        self.bot_token = os.getenv("TELEGRAM_BOT_TOKEN", config.bot_token)
        self.chat_id = os.getenv("TELEGRAM_CHAT_ID", config.chat_id)
        self.session = session
        self.logger = logger

    @property
    def enabled(self) -> bool:
        return bool(self.bot_token and self.chat_id)

    async def send_deal(
        self,
        *,
        name: str,
        price: float,
        discount: float,
        product_url: str,
        image_url: str | None,
    ) -> None:
        if not self.enabled:
            return

        caption = (
            "QA DEAL TRIGGER\n"
            f"Product: {name}\n"
            f"Price: ₹{price:,.2f}\n"
            f"Discount: {discount:.1f}%\n"
            f"URL: {product_url}"
        )
        base = f"https://api.telegram.org/bot{self.bot_token}"
        try:
            if image_url:
                endpoint = f"{base}/sendPhoto"
                payload = {
                    "chat_id": self.chat_id,
                    "photo": image_url,
                    "caption": caption,
                }
            else:
                endpoint = f"{base}/sendMessage"
                payload = {
                    "chat_id": self.chat_id,
                    "text": caption,
                    "disable_web_page_preview": False,
                }
            async with self.session.post(endpoint, json=payload) as response:
                if response.status >= 300:
                    raise RuntimeError(
                        f"Telegram HTTP {response.status}: {(await response.text())[:300]}"
                    )
        except Exception as error:
            log_event(
                self.logger,
                logging.WARNING,
                "telegram_failure",
                str(error),
                error_type=type(error).__name__,
            )
