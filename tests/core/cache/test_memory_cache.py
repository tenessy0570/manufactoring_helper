import pytest

from app.core.cache import MemoryCache
from tests.helpers import FakeClock


async def test_returns_stored_value() -> None:
    cache = MemoryCache(max_items=10)

    await cache.set("key", {"a": 1}, ttl_seconds=60)

    assert await cache.get("key") == {"a": 1}


async def test_missing_key_returns_none() -> None:
    assert await MemoryCache(max_items=10).get("missing") is None


async def test_value_expires_after_ttl() -> None:
    clock = FakeClock()
    cache = MemoryCache(max_items=10, clock=clock)
    await cache.set("key", "value", ttl_seconds=10)

    clock.advance(9)
    assert await cache.get("key") == "value"
    clock.advance(1)
    assert await cache.get("key") is None


async def test_delete_removes_value_and_ignores_missing_keys() -> None:
    cache = MemoryCache(max_items=10)
    await cache.set("key", "value", ttl_seconds=60)

    await cache.delete("key")
    await cache.delete("never-existed")

    assert await cache.get("key") is None


async def test_least_recently_used_item_is_evicted_first() -> None:
    cache = MemoryCache(max_items=2)
    await cache.set("a", 1, ttl_seconds=60)
    await cache.set("b", 2, ttl_seconds=60)
    await cache.get("a")

    await cache.set("c", 3, ttl_seconds=60)

    assert await cache.get("a") == 1
    assert await cache.get("b") is None
    assert await cache.get("c") == 3


async def test_overwriting_a_key_does_not_grow_the_cache() -> None:
    cache = MemoryCache(max_items=2)
    await cache.set("a", 1, ttl_seconds=60)
    await cache.set("a", 2, ttl_seconds=60)
    await cache.set("b", 3, ttl_seconds=60)

    assert await cache.get("a") == 2
    assert await cache.get("b") == 3


def test_max_items_must_be_positive() -> None:
    with pytest.raises(ValueError, match="max_items"):
        MemoryCache(max_items=0)


async def test_ttl_must_be_positive() -> None:
    with pytest.raises(ValueError, match="ttl_seconds"):
        await MemoryCache(max_items=1).set("key", "value", ttl_seconds=0)
