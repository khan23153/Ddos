from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Awaitable, Callable
from typing import TypeVar

import aiohttp

from .errors import ApiError
from .logging_utils import log_event

T = TypeVar("T")


def is_retryable(error: Exception) -> bool:
    if isinstance(error, (aiohttp.ClientError, asyncio.TimeoutError)):
        return True
    return isinstance(error, ApiError) and error.status in {
        408,
        409,
        425,
        429,
        500,
        502,
        503,
        504,
    }


async def with_retry(
    operation: Callable[[], Awaitable[T]],
    *,
    logger: logging.Logger,
    event: str,
    account: str | None = None,
    max_retries: int = 2,
) -> T:
    for attempt in range(max_retries + 1):
        try:
            return await operation()
        except Exception as error:
            if attempt >= max_retries or not is_retryable(error):
                raise
            delay = min(8.0, 2**attempt + random.uniform(0.1, 0.8))
            log_event(
                logger,
                logging.WARNING,
                event,
                f"Retrying after error: {error}",
                account=account,
                attempt=attempt + 1,
                error_type=type(error).__name__,
            )
            await asyncio.sleep(delay)
    raise AssertionError("unreachable")
