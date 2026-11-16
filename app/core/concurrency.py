import asyncio
from collections.abc import Awaitable, Iterable


async def gather_all[T](awaitables: Iterable[Awaitable[T]]) -> list[T]:
    """Runs awaitables concurrently, returns results in order, cancels the rest on first failure."""
    try:
        async with asyncio.TaskGroup() as group:
            tasks = [group.create_task(_as_coroutine(awaitable)) for awaitable in awaitables]
    except ExceptionGroup as error:
        raise error.exceptions[0] from error
    return [task.result() for task in tasks]


async def _as_coroutine[T](awaitable: Awaitable[T]) -> T:
    return await awaitable
