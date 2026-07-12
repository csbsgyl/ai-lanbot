from __future__ import annotations

import asyncio
import math
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    retry_after_seconds: int = 0


class SlidingWindowRateLimiter:
    def __init__(
        self,
        *,
        limit: int,
        window_seconds: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.limit = max(1, int(limit))
        self.window_seconds = max(1.0, float(window_seconds))
        self._clock = clock
        self._events: dict[str, deque[float]] = {}
        self._lock = asyncio.Lock()
        self._next_cleanup = 0.0

    async def acquire(self, key: str) -> RateLimitDecision:
        now = self._clock()
        cutoff = now - self.window_seconds
        async with self._lock:
            if now >= self._next_cleanup:
                self._cleanup(cutoff)
                self._next_cleanup = now + self.window_seconds

            events = self._events.setdefault(str(key), deque())
            while events and events[0] <= cutoff:
                events.popleft()
            if len(events) >= self.limit:
                retry_after = max(1, math.ceil(events[0] + self.window_seconds - now))
                return RateLimitDecision(False, retry_after)

            events.append(now)
            return RateLimitDecision(True)

    def _cleanup(self, cutoff: float) -> None:
        empty_keys = []
        for key, events in self._events.items():
            while events and events[0] <= cutoff:
                events.popleft()
            if not events:
                empty_keys.append(key)
        for key in empty_keys:
            self._events.pop(key, None)
