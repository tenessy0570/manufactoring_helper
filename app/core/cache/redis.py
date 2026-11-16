import json

from pydantic import JsonValue
from redis.asyncio import Redis

from app.core.cache.base import Cache


class RedisCache(Cache):
    """Persistent cache backed by Redis. Values are stored as JSON strings."""

    def __init__(self, client: Redis, key_prefix: str = "cache:") -> None:
        self._client = client
        self._key_prefix = key_prefix

    async def get(self, key: str) -> JsonValue | None:
        raw = await self._client.get(self._namespaced(key))
        return None if raw is None else json.loads(raw)

    async def set(self, key: str, value: JsonValue, ttl_seconds: int) -> None:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        await self._client.set(self._namespaced(key), json.dumps(value), ex=ttl_seconds)

    async def delete(self, key: str) -> None:
        await self._client.delete(self._namespaced(key))

    def _namespaced(self, key: str) -> str:
        return f"{self._key_prefix}{key}"
