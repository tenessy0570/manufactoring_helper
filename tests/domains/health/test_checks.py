from pathlib import Path

import pytest
from fakeredis import FakeAsyncRedis
from sqlalchemy.ext.asyncio import create_async_engine

from app.domains.health.checks import DatabaseHealthCheck, RedisHealthCheck


async def test_database_check_passes_when_query_succeeds() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    await DatabaseHealthCheck(engine).probe()

    await engine.dispose()


async def test_database_check_raises_when_database_is_unreachable(
    tmp_path: Path,
) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/missing-dir/db.sqlite")

    with pytest.raises(Exception):  # noqa: B017, PT011 - any driver error means unhealthy
        await DatabaseHealthCheck(engine).probe()

    await engine.dispose()


async def test_redis_check_passes_when_ping_succeeds() -> None:
    await RedisHealthCheck(FakeAsyncRedis(decode_responses=True)).probe()


async def test_redis_check_raises_when_ping_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeAsyncRedis(decode_responses=True)

    async def failing_ping() -> bool:
        raise ConnectionError("down")

    monkeypatch.setattr(client, "ping", failing_ping)

    with pytest.raises(ConnectionError):
        await RedisHealthCheck(client).probe()
