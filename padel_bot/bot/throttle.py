"""In-memory sliding-window rate limiter keyed by Telegram user id."""

import time
from collections import deque

from cachetools import TTLCache


class RateLimiter:
    def __init__(self, max_events: int, per_seconds: float, max_keys: int = 10_000) -> None:
        self.max_events = max_events
        self.per_seconds = per_seconds
        # Idle users disappear after the window, so memory stays bounded.
        self._events: TTLCache[int, deque[float]] = TTLCache(maxsize=max_keys, ttl=per_seconds)

    def allow(self, key: int, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        events = self._events.get(key) or deque()
        while events and now - events[0] >= self.per_seconds:
            events.popleft()
        allowed = len(events) < self.max_events
        if allowed:
            events.append(now)
        self._events[key] = events
        return allowed
