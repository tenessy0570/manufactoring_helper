from unittest.mock import AsyncMock

import pytest

from app.workers.refresh import with_retry_delay


async def test_failure_delay_survives_new_worker_context_and_does_not_retry_early() -> None:
    redis = AsyncMock()
    redis.exists.return_value = False
    operation = AsyncMock(side_effect=ConnectionError("offline"))
    with pytest.raises(ConnectionError):
        await with_retry_delay({"redis": redis}, "market:jita", operation)
    redis.set.assert_awaited_once_with("refresh:retry:market:jita", "1", ex=300)
    redis.exists.return_value = True
    assert await with_retry_delay({"redis": redis}, "market:jita", operation) is None
    assert operation.await_count == 1
    redis.exists.return_value = False
    operation.side_effect = None
    operation.return_value = 42
    assert await with_retry_delay({"redis": redis}, "market:jita", operation) == 42
    assert operation.await_count == 2


async def test_operation_without_redis_for_isolated_service_context() -> None:
    operation = AsyncMock(return_value=3)
    assert await with_retry_delay({}, "catalog", operation) == 3
    operation.side_effect = RuntimeError("failed")
    with pytest.raises(RuntimeError):
        await with_retry_delay({}, "catalog", operation)
