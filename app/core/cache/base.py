from abc import ABC, abstractmethod

from pydantic import JsonValue


class Cache(ABC):
    """Key-value cache for JSON-serializable values. None is reserved for a cache miss."""

    @abstractmethod
    async def get(self, key: str) -> JsonValue | None: ...

    @abstractmethod
    async def set(self, key: str, value: JsonValue, ttl_seconds: int) -> None: ...

    @abstractmethod
    async def delete(self, key: str) -> None: ...
