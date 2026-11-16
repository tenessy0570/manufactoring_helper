from collections.abc import AsyncIterator, Sequence
from datetime import date, timedelta
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock

import httpx
import pytest
import respx
from dishka import Provider, Scope, make_async_container
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core.orm import Base
from app.core.repository import SQLAlchemyUnitOfWork
from app.domains.catalog.repository import SQLItemTypeRepository
from app.domains.history.gateway import EsiHistoryGateway, HistoryGateway
from app.domains.history.models import HistoryDay, HistoryDownload, HistoryState, LiquidityQuery
from app.domains.history.repository import HistoryRepository, SQLHistoryRepository
from app.domains.history.service import HistoryService, HistorySyncService
from app.infrastructure.esi import EsiClient
from app.main import create_app
from tests.domains.catalog.test_catalog import NOW, item
from tests.helpers import make_settings

REGION = 10000002
EXPIRES = NOW + timedelta(days=1)


def day(days_ago: int = 1, **kwargs: Any) -> HistoryDay:
    return HistoryDay.model_validate(
        {
            "date": NOW.date() - timedelta(days=days_ago),
            "average": "10.25",
            "highest": "12",
            "lowest": "9",
            "volume": 20,
            "order_count": 3,
            **kwargs,
        }
    )


def state(region: int = REGION, type_id: int = 10) -> HistoryState:
    return HistoryState(region_id=region, type_id=type_id, synced_at=NOW, expires_at=EXPIRES)


@pytest.fixture
async def session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with AsyncSession(engine, expire_on_commit=False) as session:
        yield session
    await engine.dispose()


async def seed(session: AsyncSession) -> SQLHistoryRepository:
    catalog = SQLItemTypeRepository(session)
    await catalog.upsert_many(
        [
            item(10),
            item(20, name="Drone", category="Drones", is_rig=False, meta_group_id=1),
            item(30),
            item(40, is_active=False),
        ]
    )
    repository = SQLHistoryRepository(session)
    await repository.replace(state(), [day(), day(2), day(20), day(0)])
    await repository.replace(state(type_id=20), [day(volume=0), day(2, volume=0)])
    await repository.replace(state(region=10000043), [day(average="100", volume=100)])
    return repository


async def test_liquidity_calendar_window_and_missing_history(session: AsyncSession) -> None:
    repository = await seed(session)
    values, count = await repository.liquidity(LiquidityQuery(days=2), NOW)
    assert count == 3
    assert values[0].data_days == 2
    assert values[0].daily_units == Decimal(20)
    assert values[0].daily_isk_volume == Decimal("205")
    assert values[1].daily_units == 0
    assert values[2].data_days == 0
    assert values[2].daily_isk_volume is None
    values, _ = await repository.liquidity(LiquidityQuery(days=4, type_ids=[10]), NOW)
    assert values[0].daily_units == Decimal(10)
    assert values[0].daily_isk_volume == Decimal("102.5")
    values, _ = await repository.liquidity(
        LiquidityQuery(hub_id="amarr", days=2, type_ids=[10]), NOW
    )
    assert values[0].daily_isk_volume == Decimal(5000)


@pytest.mark.parametrize(
    ("kwargs", "ids"),
    [
        ({"type_ids": [10]}, [10]),
        ({"type_ids": []}, []),
        ({"exclude_type_ids": [10]}, [20, 30]),
        ({"search": "drone"}, [20]),
        ({"categories": ["Drones"]}, [20]),
        ({"meta_group_ids": [2]}, [10, 30]),
        ({"is_rig": False}, [20]),
        ({"has_history": True}, [10, 20]),
        ({"has_history": False}, [30]),
        ({"min_daily_units": 1}, [10]),
        ({"max_daily_units": 1}, [20]),
        ({"min_daily_isk_volume": 1}, [10]),
        ({"max_daily_isk_volume": 1}, [20]),
        ({"fresh_only": True}, [10, 20]),
        ({"limit": 1, "offset": 1}, [20]),
    ],
)
async def test_filters(session: AsyncSession, kwargs: dict[str, Any], ids: list[int]) -> None:
    repository = await seed(session)
    values, total = await repository.liquidity(LiquidityQuery(days=2, **kwargs), NOW)
    assert [value.type_id for value in values] == ids
    assert total == (3 if "offset" in kwargs else len(ids))


async def test_replace_series_hub_isolation_and_rollback(session: AsyncSession) -> None:
    repository = SQLHistoryRepository(session)
    assert await repository.state(REGION, 10) is None
    await repository.replace(state(), [day(number) for number in range(1, 206)])
    await repository.replace(state(region=10000043), [day()])
    await session.commit()
    assert await repository.state(REGION, 10) == state()
    assert len(await repository.series(REGION, 10, date(2020, 1, 1), NOW.date())) == 205
    await repository.replace(state(), [])
    assert await repository.series(REGION, 10, date(2020, 1, 1), NOW.date()) == []
    await session.rollback()
    assert len(await repository.series(REGION, 10, date(2020, 1, 1), NOW.date())) == 205
    assert len(await repository.series(10000043, 10, date(2020, 1, 1), NOW.date())) == 1


@pytest.mark.parametrize(
    "kwargs",
    [
        {"min_daily_units": 10, "max_daily_units": 1},
        {"min_daily_isk_volume": 10, "max_daily_isk_volume": 1},
    ],
)
def test_invalid_ranges(kwargs: dict[str, Any]) -> None:
    with pytest.raises(ValueError, match="Minimum"):
        LiquidityQuery.model_validate(kwargs)


class FakeRepository(HistoryRepository):
    def __init__(self) -> None:
        self.current: HistoryState | None = None
        self.days: list[HistoryDay] = []

    async def state(self, region_id: int, type_id: int) -> HistoryState | None:
        return self.current

    async def replace(self, snapshot: HistoryState, days: Sequence[HistoryDay]) -> None:
        self.current, self.days = snapshot, list(days)

    async def series(
        self, region_id: int, type_id: int, start: date, end: date
    ) -> list[HistoryDay]:
        return [value for value in self.days if start <= value.date <= end]

    async def liquidity(self, query: LiquidityQuery, now: Any) -> tuple[list[Any], int]:
        return [], 0


async def test_sync_skips_fresh_filters_today_and_handles_empty() -> None:
    repository = FakeRepository()
    gateway = AsyncMock(spec=HistoryGateway)
    gateway.fetch.return_value = HistoryDownload(days=[day(), day(0)], expires_at=EXPIRES)
    uow = AsyncMock(spec=SQLAlchemyUnitOfWork)
    service = HistorySyncService(repository, gateway, uow, lambda: NOW)
    assert await service.sync_if_stale(REGION, 10)
    assert repository.days == [day()]
    assert not await service.sync_if_stale(REGION, 10)
    gateway.fetch.assert_awaited_once_with(REGION, 10)
    gateway.fetch.return_value = HistoryDownload(days=[], expires_at=EXPIRES + timedelta(days=1))
    service = HistorySyncService(repository, gateway, uow, lambda: EXPIRES)
    assert await service.sync_if_stale(REGION, 10)
    assert repository.days == []
    assert not await service.sync_if_stale(REGION, 10)


async def test_download_failure_preserves_data_and_write_failure_rolls_back() -> None:
    repository = FakeRepository()
    repository.days = [day()]
    gateway = AsyncMock(spec=HistoryGateway)
    gateway.fetch.side_effect = ConnectionError("offline")
    uow = AsyncMock(spec=SQLAlchemyUnitOfWork)
    service = HistorySyncService(repository, gateway, uow)
    with pytest.raises(ConnectionError, match="offline"):
        await service.sync_if_stale(REGION, 10)
    assert repository.days == [day()]
    uow.commit.assert_not_awaited()
    gateway.fetch.side_effect = None
    gateway.fetch.return_value = HistoryDownload(days=[day()], expires_at=EXPIRES)
    uow.commit.side_effect = RuntimeError("write failed")
    with pytest.raises(RuntimeError, match="write failed"):
        await service.sync_if_stale(REGION, 10)
    uow.rollback.assert_awaited_once()


async def test_services_and_api(session: AsyncSession) -> None:
    repository = await seed(session)
    service = HistoryService(repository, lambda: NOW)
    assert not (await service.series("jita", 10, 2)).stale
    assert (await service.series("jita", 30, 2)).stale
    provider = Provider(scope=Scope.REQUEST)
    provider.provide(lambda: service, provides=HistoryService)
    container = make_async_container(provider)
    app = create_app(container=container, settings=make_settings())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://test"
    ) as client:
        response = await client.get("/api/v1/market/liquidity?days=2&min_daily_units=1")
        assert response.status_code == 200, response.text
        assert response.json()["total"] == 1
        assert response.json()["scope"] == "region"
        assert (await client.get("/api/v1/market/history/10?hub_id=amarr&days=2")).json()["days"][
            0
        ]["volume"] == 100
        for path in ("liquidity?days=0", "history/0", "liquidity?hub_id=invalid"):
            assert (await client.get(f"/api/v1/market/{path}")).status_code == 422
    await container.close()


@pytest.mark.parametrize("expires", [None, "invalid", "Mon, 16 Nov 2026 01:00:00 GMT"])
async def test_gateway_decimal_expiry_and_duplicate_dates(expires: str | None) -> None:
    async with httpx.AsyncClient(base_url="https://test") as http:
        gateway = EsiHistoryGateway(EsiClient(http, 1, 0, lambda: "2026-11-16"), clock=lambda: NOW)
        with respx.mock:
            route = respx.get(
                f"https://test/markets/{REGION}/history/", params={"type_id": 10}
            ).respond(
                200,
                json=[day().model_dump(mode="json")],
                headers={"Expires": expires} if expires else {},
            )
            result = await gateway.fetch(REGION, 10)
            assert result.days[0].average == Decimal("10.25")
            assert result.expires_at == (
                NOW + timedelta(hours=1) if expires and expires != "invalid" else EXPIRES
            )
            route.respond(200, json=[day().model_dump(mode="json")] * 2)
            with pytest.raises(ValueError, match="Duplicate dates"):
                await gateway.fetch(REGION, 10)


@pytest.mark.parametrize(
    "body", [{"error": "Type not found!"}, {"error": "Unknown route"}, "invalid"]
)
async def test_history_missing_type_is_cached_but_other_404_errors_propagate(body: object) -> None:
    from app.infrastructure.http import HttpStatusError

    async with httpx.AsyncClient(base_url="https://test") as http:
        gateway = EsiHistoryGateway(EsiClient(http, 1, 0, lambda: "2026-11-16"), clock=lambda: NOW)
        with respx.mock:
            respx.get(f"https://test/markets/{REGION}/history/").respond(404, json=body)
            if body == {"error": "Type not found!"}:
                result = await gateway.fetch(REGION, 406)
                assert result.days == []
                assert result.expires_at == EXPIRES
            else:
                with pytest.raises(HttpStatusError):
                    await gateway.fetch(REGION, 406)
