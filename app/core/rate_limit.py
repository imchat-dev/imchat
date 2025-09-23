# app/core/rate_limit.py
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Dict, Deque
from collections import deque


@dataclass
class RateLimitState:
    bucket: Deque[float]


class RateLimitError(Exception):
    """Raised when a client exceeds the configured rate limit."""

    def __init__(self, retry_after: float) -> None:
        self.retry_after = max(retry_after, 0.0)
        super().__init__(f"Rate limit exceeded. Retry after {self.retry_after:.1f}s")


class RateLimiter:
    """Simple in-memory rate limiter suitable for a single FastAPI instance."""

    def __init__(self, max_requests: int, window_seconds: int) -> None:
        if max_requests <= 0 or window_seconds <= 0:
            raise ValueError("RateLimiter requires positive thresholds")
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._states: Dict[str, RateLimitState] = {}
        self._lock = asyncio.Lock()

    async def check(self, key: str) -> None:
        now = time.monotonic()
        async with self._lock:
            state = self._states.get(key)
            if state is None:
                state = RateLimitState(bucket=deque(maxlen=self.max_requests))
                self._states[key] = state

            bucket = state.bucket
            # Evict expired timestamps
            while bucket and now - bucket[0] > self.window_seconds:
                bucket.popleft()

            if len(bucket) >= self.max_requests:
                retry_after = self.window_seconds - (now - bucket[0])
                raise RateLimitError(retry_after)

            bucket.append(now)

    async def reset(self, key: str) -> None:
        async with self._lock:
            self._states.pop(key, None)

    async def clear_expired(self) -> None:
        now = time.monotonic()
        async with self._lock:
            expired = [
                key
                for key, state in self._states.items()
                if not state.bucket or now - state.bucket[-1] > self.window_seconds
            ]
            for key in expired:
                self._states.pop(key, None)
