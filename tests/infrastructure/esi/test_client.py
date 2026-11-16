from datetime import UTC, datetime, timedelta, timezone

import httpx
import pytest

from app.infrastructure.esi.client import EsiClient, make_compatibility_date_provider


def test_date_provider_rolls_over_and_respects_timezone() -> None:
    now = datetime(2026, 11, 16, 10, 59, tzinfo=UTC)
    provider = make_compatibility_date_provider("", lambda: now)
    assert provider() == "2026-11-15"
    now += timedelta(minutes=1)
    assert provider() == "2026-11-16"
    now = now.astimezone(timezone(timedelta(hours=7)))
    assert provider() == "2026-11-16"
    assert make_compatibility_date_provider("2025-01-01")() == "2025-01-01"


@pytest.mark.parametrize(
    ("headers", "expected"),
    [
        ({}, []),
        ({"X-Ratelimit-Remaining": "4"}, [2.0]),
        ({"X-Ratelimit-Remaining": "5"}, []),
        ({"X-Esi-Error-Limit-Remain": "14"}, [2.0]),
        ({"X-Esi-Error-Limit-Remain": "15"}, []),
        ({"X-Ratelimit-Remaining": "invalid"}, []),
        ({"X-Ratelimit-Remaining": "0", "X-Esi-Error-Limit-Remain": "0"}, [2.0]),
    ],
)
async def test_headers_and_back_pressure(headers: dict[str, str], expected: list[float]) -> None:
    delays: list[float] = []

    async def sleep(delay: float) -> None:
        delays.append(delay)

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["X-Compatibility-Date"] == "2026-11-16"
        return httpx.Response(200, headers=headers, json=[])

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = EsiClient(http, 1, 0, lambda: "2026-11-16", sleep)
        assert await client.get_json("https://test") == []
    assert delays == expected


async def test_default_sleep_can_be_used_without_back_pressure() -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={}))
    ) as http:
        client = EsiClient(http, 1, 0, lambda: "2026-11-16")
        assert await client.get_json("https://test") == {}
