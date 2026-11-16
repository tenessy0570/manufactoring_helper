import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from pydantic import JsonValue

from app.core.cache.base import Cache


@dataclass
class _KeyLock:
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    users: int = 0


class CacheService:
    """Read-through cache access with single-flight loading.

    Concurrent callers asking for the same missing key share one loader call, which prevents
    cache stampedes. Single-flight is per process; other processes may still load in parallel.
    """

    def __init__(self, cache: Cache) -> None:
        self._cache = cache
        self._key_locks: dict[str, _KeyLock] = {}

    async def get_or_load(
        self,
        key: str,
        loader: Callable[[], Awaitable[JsonValue]],
        ttl_seconds: int,
    ) -> JsonValue:
        cached = await self._cache.get(key)
        if cached is not None:
            return cached

        key_lock = self._key_locks.setdefault(key, _KeyLock())
        key_lock.users += 1
        try:
            async with key_lock.lock:
                cached = await self._cache.get(key)
                if cached is not None:
                    return cached
                value = await loader()
                await self._cache.set(key, value, ttl_seconds)
                return value
        finally:
            key_lock.users -= 1
            if key_lock.users == 0:
                del self._key_locks[key]
