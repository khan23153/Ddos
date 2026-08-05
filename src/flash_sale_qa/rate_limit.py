from __future__ import annotations

import asyncio
import time
from collections import deque


class SlidingWindowRateLimiter:
    def __init__(self, requests_per_second: float) -> None:
        self.limit = max(1, int(requests_per_second))
        self.timestamps: deque[float] = deque()
        self.lock = asyncio.Lock()

    async def acquire(self) -> None:
        while True:
            async with self.lock:
                now = time.monotonic()
                while self.timestamps and now - self.timestamps[0] >= 1.0:
                    self.timestamps.popleft()
                if len(self.timestamps) < self.limit:
                    self.timestamps.append(now)
                    return
                delay = 1.0 - (now - self.timestamps[0])
            await asyncio.sleep(max(0.01, delay))
