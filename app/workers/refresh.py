from collections.abc import Awaitable, Callable
from typing import Any

from app.core.config import DEFAULT_REFRESH

RETRY_DELAY_SECONDS = DEFAULT_REFRESH.retry_seconds


async def with_retry_delay[T](
    ctx: dict[str, Any], key: str, operation: Callable[[], Awaitable[T]]
) -> T | None:
    redis = ctx.get("redis")
    retry_key = f"refresh:retry:{key}"
    if redis is not None and await redis.exists(retry_key):
        return None
    try:
        return await operation()
    except Exception:
        if redis is not None:
            await redis.set(
                retry_key, "1", ex=ctx.get("refresh_retry_seconds", RETRY_DELAY_SECONDS)
            )
        raise
