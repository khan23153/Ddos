from __future__ import annotations

import asyncio
import time


class SlidingWindowRateLimiter:
    def __init__(self, requests_per_second: float) -> None:
        self.interval = 1.0 / max(0.001, requests_per_second)
        self.next_allowed = 0.0
        self.lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self.lock:
            now = time.monotonic()
            delay = max(0.0, self.next_allowed - now)
            if delay:
                await asyncio.sleep(delay)
                now = time.monotonic()
            self.next_allowed = max(now, self.next_allowed) + self.interval
