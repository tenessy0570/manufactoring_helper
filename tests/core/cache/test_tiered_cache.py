import logging

import pytest

from app.core.cache import MemoryCache, TieredCache
from tests.helpers import FailingCache, FakeClock


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def memory(clock: FakeClock) -> MemoryCache:
    return MemoryCache(max_items=10, clock=clock)


@pytest.fixture
def persistent(clock: FakeClock) -> MemoryCache:
    return MemoryCache(max_items=10, clock=clock)


async def test_set_writes_to_both_tiers(memory: MemoryCache, persistent: MemoryCache) -> None:
    cache = TieredCache(memory, persistent, memory_ttl_seconds=60)

    await cache.set("key", "value", ttl_seconds=600)

    assert await memory.get("key") == "value"
    assert await persistent.get("key") == "value"


async def test_persistent_hit_is_promoted_to_memory(
    memory: MemoryCache, persistent: MemoryCache
) -> None:
    cache = TieredCache(memory, persistent, memory_ttl_seconds=60)
    await persistent.set("key", "value", ttl_seconds=600)

    assert await cache.get("key") == "value"
    assert await memory.get("key") == "value"


async def test_memory_tier_ttl_is_capped(
    memory: MemoryCache, persistent: MemoryCache, clock: FakeClock
) -> None:
    cache = TieredCache(memory, persistent, memory_ttl_seconds=60)
    await cache.set("key", "value", ttl_seconds=600)

    clock.advance(61)

    assert await memory.get("key") is None
    assert await cache.get("key") == "value"


async def test_miss_in_both_tiers_returns_none(
    memory: MemoryCache, persistent: MemoryCache
) -> None:
    assert await TieredCache(memory, persistent, memory_ttl_seconds=60).get("key") is None


async def test_delete_removes_from_both_tiers(memory: MemoryCache, persistent: MemoryCache) -> None:
    cache = TieredCache(memory, persistent, memory_ttl_seconds=60)
    await cache.set("key", "value", ttl_seconds=600)

    await cache.delete("key")

    assert await memory.get("key") is None
    assert await persistent.get("key") is None


async def test_persistent_failures_degrade_to_memory_only(
    memory: MemoryCache, caplog: pytest.LogCaptureFixture
) -> None:
    cache = TieredCache(memory, FailingCache(), memory_ttl_seconds=60)

    with caplog.at_level(logging.WARNING):
        await cache.set("key", "value", ttl_seconds=600)
        assert await cache.get("key") == "value"
        assert await cache.get("other") is None
        await cache.delete("key")

    assert await memory.get("key") is None
    assert "Persistent cache write failed for key" in caplog.text
    assert "Persistent cache read failed for other" in caplog.text
    assert "Persistent cache delete failed for key" in caplog.text
