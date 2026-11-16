import asyncio
import json

import httpx
import pytest
import respx

from app.infrastructure.everef.client import EverefClient
from app.infrastructure.http import HttpStatusError, ResilientHttpClient


@pytest.mark.parametrize("status", [420, 429, 500, 502, 503, 504])
async def test_retryable_status_recovers(status: int) -> None:
    delays: list[float] = []

    async def sleep(delay: float) -> None:
        delays.append(delay)

    async with httpx.AsyncClient(base_url="https://test") as http:
        client = ResilientHttpClient(http, 2, 2, sleep)
        with respx.mock:
            route = respx.get("https://test/data").mock(
                side_effect=[httpx.Response(status), httpx.Response(200, json={"ok": True})]
            )
            assert await client.get_json("/data") == {"ok": True}
            assert route.call_count == 2
    assert delays == [1.0]


@pytest.mark.parametrize(("retry_after", "expected"), [("7", 7.0), ("invalid", 1.0)])
async def test_retry_after_and_exhaustion(retry_after: str, expected: float) -> None:
    delays: list[float] = []

    async def sleep(delay: float) -> None:
        delays.append(delay)

    async with httpx.AsyncClient(base_url="https://test") as http:
        client = ResilientHttpClient(http, 1, 1, sleep)
        with respx.mock:
            route = respx.get("https://test/data").respond(
                429, headers={"Retry-After": retry_after}
            )
            with pytest.raises(HttpStatusError) as error:
                await client.get_json("/data")
            assert error.value.status_code == 429
            assert error.value.url == "https://test/data"
            assert route.call_count == 2
    assert delays == [expected]


async def test_non_retryable_error_is_not_retried() -> None:
    async with httpx.AsyncClient(base_url="https://test") as http:
        client = ResilientHttpClient(http, 1, 4)
        with respx.mock:
            route = respx.get("https://test/missing").respond(404)
            with pytest.raises(HttpStatusError):
                await client.get_json("/missing")
            assert route.call_count == 1


async def test_transport_retries_backoff_cap_and_final_error() -> None:
    delays: list[float] = []

    async def sleep(delay: float) -> None:
        delays.append(delay)

    async with httpx.AsyncClient(base_url="https://test") as http:
        client = ResilientHttpClient(http, 1, 7, sleep)
        with respx.mock:
            route = respx.get("https://test/data").mock(side_effect=httpx.ConnectError("down"))
            with pytest.raises(httpx.ConnectError):
                await client.get_json("/data")
            assert route.call_count == 8
    assert delays == [1, 2, 4, 8, 16, 30, 30]


async def test_post_body_query_params_and_close() -> None:
    http = httpx.AsyncClient(base_url="https://test")
    client = EverefClient(http, 1, 0)
    with respx.mock:
        post = respx.post("https://test/names").respond(200, json=["name"])
        assert await client.post_json("/names", [42]) == ["name"]
        assert json.loads(post.calls[0].request.content) == [42]
        respx.get("https://test/data", params={"page": 2}).respond(200, json=[])
        assert await client.get_json("/data", params={"page": 2}) == []
    await client.aclose()
    assert http.is_closed


async def test_concurrency_is_bounded() -> None:
    active = 0
    peak = 0
    entered = asyncio.Event()
    release = asyncio.Event()

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        if active == 2:
            entered.set()
        await release.wait()
        active -= 1
        return httpx.Response(200, json={})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = ResilientHttpClient(http, 2, 0)
        tasks = [asyncio.create_task(client.get_json("https://test")) for _ in range(6)]
        try:
            await asyncio.wait_for(entered.wait(), timeout=2)
            assert peak == 2
        finally:
            release.set()
            await asyncio.gather(*tasks)
    assert peak == 2


@pytest.mark.parametrize(("concurrency", "retries"), [(0, 1), (-1, 1), (1, -1)])
async def test_invalid_limits_are_rejected(concurrency: int, retries: int) -> None:
    async with httpx.AsyncClient() as http:
        with pytest.raises(ValueError, match="must be"):
            ResilientHttpClient(http, concurrency, retries)
