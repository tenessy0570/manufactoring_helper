import time
from collections import OrderedDict
from collections.abc import Callable

from pydantic import JsonValue

from app.core.cache.base import Cache


class MemoryCache(Cache):
    """In-process LRU cache with per-item TTL."""

    def __init__(self, max_items: int, clock: Callable[[], float] = time.monotonic) -> None:
        if max_items <= 0:
            raise ValueError("max_items must be positive")
        self._max_items = max_items
        self._clock = clock
        self._items: OrderedDict[str, tuple[float, JsonValue]] = OrderedDict()

    async def get(self, key: str) -> JsonValue | None:
        entry = self._items.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        if expires_at <= self._clock():
            del self._items[key]
            return None
        self._items.move_to_end(key)
        return value

    async def set(self, key: str, value: JsonValue, ttl_seconds: int) -> None:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        self._items[key] = (self._clock() + ttl_seconds, value)
        self._items.move_to_end(key)
        while len(self._items) > self._max_items:
            self._items.popitem(last=False)

    async def delete(self, key: str) -> None:
        self._items.pop(key, None)
