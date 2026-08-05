from __future__ import annotations

import logging
import time
from typing import Any
from urllib.parse import urljoin, urlparse

import aiohttp

from .config import Config
from .errors import ApiError
from .logging_utils import log_event
from .rate_limit import SlidingWindowRateLimiter


class StagingClient:
    def __init__(
        self,
        config: Config,
        session: aiohttp.ClientSession,
        limiter: SlidingWindowRateLimiter,
        logger: logging.Logger,
    ) -> None:
        self.config = config
        self.session = session
        self.limiter = limiter
        self.logger = logger

    def absolute_url(self, path_or_url: str) -> str:
        url = urljoin(self.config.base_url, path_or_url)
        host = (urlparse(url).hostname or "").lower()
        if host not in self.config.allowed_hosts:
            raise ApiError(f"Request host {host!r} is not allowlisted")
        return url

    async def request(
        self,
        method: str,
        path_or_url: str,
        *,
        token: str | None = None,
        json_body: dict[str, Any] | None = None,
        expected: set[int] | None = None,
    ) -> dict[str, Any]:
        await self.limiter.acquire()
        url = self.absolute_url(path_or_url)
        headers = {
            "Accept": "application/json",
            "User-Agent": "Authorized-Flash-Sale-QA/1.0",
            "X-QA-Client": "flash-sale-harness",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"

        started = time.monotonic()
        async with self.session.request(
            method,
            url,
            headers=headers,
            json=json_body,
        ) as response:
            content_type = response.headers.get("Content-Type", "")
            if "application/json" in content_type:
                body: Any = await response.json(content_type=None)
            else:
                body = {"text": (await response.text())[:2000]}

            duration_ms = int((time.monotonic() - started) * 1000)
            log_event(
                self.logger,
                logging.INFO,
                "http_request",
                f"{method} {url} returned {response.status}",
                status=response.status,
                duration_ms=duration_ms,
            )

            accepted = expected or {200}
            if response.status not in accepted:
                raise ApiError(
                    f"{method} {url} returned HTTP {response.status}",
                    status=response.status,
                    body=body,
                )
            if not isinstance(body, dict):
                raise ApiError("Expected a JSON object response", body=body)
            return body
