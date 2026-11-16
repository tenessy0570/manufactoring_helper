import asyncio

import pytest

from app.core.concurrency import gather_all


async def test_results_preserve_input_order() -> None:
    async def value(number: int) -> int:
        await asyncio.sleep(0)
        return number

    assert await gather_all(value(number) for number in [3, 1, 2]) == [3, 1, 2]
    assert await gather_all([]) == []


async def test_failure_cancels_and_awaits_other_tasks() -> None:
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def blocked() -> None:
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    async def fail() -> None:
        await started.wait()
        raise ValueError("failed")

    with pytest.raises(ValueError, match="failed"):
        await gather_all([blocked(), fail()])
    assert cancelled.is_set()
