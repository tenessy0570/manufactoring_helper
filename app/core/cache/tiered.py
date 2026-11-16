import logging

from pydantic import JsonValue

from app.core.cache.base import Cache

logger = logging.getLogger(__name__)


class TieredCache(Cache):
    """Fast in-memory cache in front of a persistent one.

    The persistent tier is best-effort: if it fails, the cache keeps serving from memory
    instead of failing the request. Entries promoted from the persistent tier live in memory
    for at most memory_ttl_seconds, which bounds how stale the fast tier can get.
    """

    def __init__(self, memory: Cache, persistent: Cache, memory_ttl_seconds: int) -> None:
        self._memory = memory
        self._persistent = persistent
        self._memory_ttl_seconds = memory_ttl_seconds

    async def get(self, key: str) -> JsonValue | None:
        value = await self._memory.get(key)
        if value is not None:
            return value
        value = await self._read_persistent(key)
        if value is not None:
            await self._memory.set(key, value, self._memory_ttl_seconds)
        return value

    async def set(self, key: str, value: JsonValue, ttl_seconds: int) -> None:
        await self._memory.set(key, value, min(ttl_seconds, self._memory_ttl_seconds))
        await self._write_persistent(key, value, ttl_seconds)

    async def delete(self, key: str) -> None:
        await self._memory.delete(key)
        try:
            await self._persistent.delete(key)
        except Exception:
            logger.warning("Persistent cache delete failed for %s", key, exc_info=True)

    async def _read_persistent(self, key: str) -> JsonValue | None:
        try:
            return await self._persistent.get(key)
        except Exception:
            logger.warning("Persistent cache read failed for %s", key, exc_info=True)
            return None

    async def _write_persistent(self, key: str, value: JsonValue, ttl_seconds: int) -> None:
        try:
            await self._persistent.set(key, value, ttl_seconds)
        except Exception:
            logger.warning("Persistent cache write failed for %s", key, exc_info=True)
