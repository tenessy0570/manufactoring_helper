from collections.abc import Awaitable, Callable
from typing import Any

RETRY_DELAY_SECONDS = 300


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
            await redis.set(retry_key, "1", ex=RETRY_DELAY_SECONDS)
        raise
