import asyncio

import pytest
from pydantic import JsonValue

from app.core.cache import CacheService, MemoryCache


class CountingLoader:
    def __init__(self, value: JsonValue = "loaded", delay: float = 0.0) -> None:
        self.calls = 0
        self._value = value
        self._delay = delay

    async def __call__(self) -> JsonValue:
        self.calls += 1
        await asyncio.sleep(self._delay)
        return self._value


@pytest.fixture
def service() -> CacheService:
    return CacheService(MemoryCache(max_items=10))


async def test_loads_on_miss_and_serves_from_cache_afterwards(service: CacheService) -> None:
    loader = CountingLoader()

    first = await service.get_or_load("key", loader, ttl_seconds=60)
    second = await service.get_or_load("key", loader, ttl_seconds=60)

    assert (first, second) == ("loaded", "loaded")
    assert loader.calls == 1


async def test_concurrent_callers_share_a_single_load(service: CacheService) -> None:
    loader = CountingLoader(value={"v": 1}, delay=0.01)

    results = await asyncio.gather(
        *(service.get_or_load("key", loader, ttl_seconds=60) for _ in range(10))
    )

    assert loader.calls == 1
    assert results == [{"v": 1}] * 10


async def test_different_keys_load_independently(service: CacheService) -> None:
    loader = CountingLoader()

    await asyncio.gather(
        service.get_or_load("a", loader, ttl_seconds=60),
        service.get_or_load("b", loader, ttl_seconds=60),
    )

    assert loader.calls == 2


async def test_failed_load_is_not_cached_and_does_not_block_retries(
    service: CacheService,
) -> None:
    async def failing_loader() -> JsonValue:
        raise RuntimeError("upstream down")

    with pytest.raises(RuntimeError):
        await service.get_or_load("key", failing_loader, ttl_seconds=60)

    loader = CountingLoader()
    assert await service.get_or_load("key", loader, ttl_seconds=60) == "loaded"
    assert loader.calls == 1


async def test_key_locks_are_released_after_use(service: CacheService) -> None:
    await service.get_or_load("key", CountingLoader(), ttl_seconds=60)

    assert service._key_locks == {}
