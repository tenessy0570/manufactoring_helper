import pytest
from fakeredis import FakeAsyncRedis

from app.core.cache import RedisCache


@pytest.fixture
def client() -> FakeAsyncRedis:
    return FakeAsyncRedis(decode_responses=True)


async def test_round_trips_json_values(client: FakeAsyncRedis) -> None:
    cache = RedisCache(client)

    await cache.set("key", {"prices": [1.5, 2]}, ttl_seconds=60)

    assert await cache.get("key") == {"prices": [1.5, 2]}


async def test_missing_key_returns_none(client: FakeAsyncRedis) -> None:
    assert await RedisCache(client).get("missing") is None


async def test_keys_are_namespaced_and_get_a_ttl(client: FakeAsyncRedis) -> None:
    await RedisCache(client, key_prefix="eve:").set("key", "value", ttl_seconds=30)

    assert await client.get("eve:key") == '"value"'
    assert 0 < await client.ttl("eve:key") <= 30


async def test_delete_removes_value(client: FakeAsyncRedis) -> None:
    cache = RedisCache(client)
    await cache.set("key", "value", ttl_seconds=60)

    await cache.delete("key")

    assert await cache.get("key") is None


async def test_ttl_must_be_positive(client: FakeAsyncRedis) -> None:
    with pytest.raises(ValueError, match="ttl_seconds"):
        await RedisCache(client).set("key", "value", ttl_seconds=0)
