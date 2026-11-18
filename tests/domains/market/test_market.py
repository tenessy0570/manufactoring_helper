from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime, timedelta
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
from app.domains.market.aggregation import PriceAggregator
from app.domains.market.gateway import EsiMarketGateway, MarketGateway
from app.domains.market.models import (
    HubId,
    MarketOrder,
    MarketPrice,
    MarketState,
    OrderPage,
    PriceQuery,
    get_hub,
)
from app.domains.market.repository import MarketRepository, SQLMarketRepository
from app.domains.market.service import MarketService, MarketSyncService
from app.infrastructure.esi import EsiClient
from app.main import create_app
from tests.helpers import make_settings

NOW = datetime(2026, 11, 16, tzinfo=UTC)
EXPIRES = NOW + timedelta(minutes=5)


def order(**kwargs: Any) -> MarketOrder:
    return MarketOrder.model_validate(
        {
            "order_id": 1,
            "type_id": 10,
            "location_id": get_hub("jita").station_id,
            "is_buy_order": False,
            "price": "10.10",
            "volume_remain": 5,
            **kwargs,
        }
    )


def price(type_id: int = 10, **kwargs: Any) -> MarketPrice:
    return MarketPrice.model_validate(
        {
            "hub_id": "jita",
            "type_id": type_id,
            "buy_price": "9.10",
            "sell_price": "10.10",
            "buy_volume": 10,
            "sell_volume": 20,
            "spread": "1.00",
            "synced_at": NOW,
            "expires_at": EXPIRES,
            **kwargs,
        }
    )


def state(hub_id: HubId = "jita", items: int = 1) -> MarketState:
    return MarketState(hub_id=hub_id, synced_at=NOW, expires_at=EXPIRES, items=items)


class FakeRepository(MarketRepository):
    def __init__(self) -> None:
        self.states: dict[HubId, MarketState] = {}
        self.prices: dict[HubId, list[MarketPrice]] = {}

    async def state(self, hub_id: HubId) -> MarketState | None:
        return self.states.get(hub_id)

    async def replace(self, snapshot: MarketState, prices: Sequence[MarketPrice]) -> None:
        self.states[snapshot.hub_id] = snapshot
        self.prices[snapshot.hub_id] = list(prices)

    async def find(self, query: PriceQuery, now: datetime) -> list[MarketPrice]:
        return self.prices.get(query.hub_id, [])[query.offset : query.offset + query.limit]

    async def count(self, query: PriceQuery, now: datetime) -> int:
        return len(self.prices.get(query.hub_id, []))


class FakeGateway(MarketGateway):
    def __init__(self, fail: bool = False, change_pages: bool = False) -> None:
        self.fail, self.change_pages = fail, change_pages
        self.calls: list[tuple[int, int]] = []

    async def get_orders(self, region_id: int, page: int) -> OrderPage:
        self.calls.append((region_id, page))
        if page == 2 and self.fail:
            raise ConnectionError("page failed")
        return OrderPage(
            orders=[order(price="10.10" if page == 1 else "9.10")],
            page=page,
            pages=3 if page == 2 and self.change_pages else 2,
            expires_at=EXPIRES if page == 1 else EXPIRES - timedelta(seconds=10),
        )


def test_best_price_aggregation_and_exact_decimal_volume() -> None:
    aggregator = PriceAggregator(get_hub("jita"), NOW, EXPIRES)
    for entry in (
        order(price="12"),
        order(price="10.10"),
        order(price="10.10", volume_remain=7),
        order(price="11"),
        order(location_id=123, price="1"),
        order(price="1", volume_remain=0),
        order(is_buy_order=True, price="8"),
        order(is_buy_order=True, price="9.10"),
        order(is_buy_order=True, price="9.10", volume_remain=3),
        order(is_buy_order=True, price="7"),
        order(type_id=20),
    ):
        aggregator.add(entry)
    prices = aggregator.finish(EXPIRES)
    assert prices[0].buy_price == Decimal("9.10")
    assert prices[0].sell_price == Decimal("10.10")
    assert prices[0].buy_volume == 8
    assert prices[0].sell_volume == 12
    assert prices[0].buy_order_count == 4
    assert prices[0].buy_orders_at_best == 2
    assert prices[0].sell_order_count == 4
    assert prices[0].sell_orders_at_best == 2
    assert prices[0].spread == Decimal("1.00")
    assert prices[1].buy_price is None
    assert prices[1].spread is None


async def test_sync_streams_pages_and_skips_until_expiry() -> None:
    repository, gateway = FakeRepository(), FakeGateway()
    uow = AsyncMock(spec=SQLAlchemyUnitOfWork)
    service = MarketSyncService(repository, gateway, uow, lambda: NOW)
    report = await service.sync_if_stale("jita")
    assert report.pages == 2
    assert gateway.calls == [(10000002, 1), (10000002, 2)]
    assert repository.prices["jita"][0].sell_price == Decimal("9.10")
    assert repository.states["jita"].expires_at == EXPIRES - timedelta(seconds=10)
    assert (await service.sync_if_stale("jita")).skipped
    uow.commit.assert_awaited_once()
    assert (await MarketService(repository).find(PriceQuery())).stale


@pytest.mark.parametrize("change_pages", [False, True])
async def test_failed_page_preserves_previous_snapshot(change_pages: bool) -> None:
    repository = FakeRepository()
    await repository.replace(state(), [price()])
    uow = AsyncMock(spec=SQLAlchemyUnitOfWork)
    service = MarketSyncService(repository, FakeGateway(not change_pages, change_pages), uow)
    with pytest.raises((ValueError, ConnectionError), match=r"page failed|pagination changed"):
        await service.sync("jita")
    assert repository.prices["jita"] == [price()]
    uow.commit.assert_not_awaited()


async def test_write_failure_rolls_back() -> None:
    uow = AsyncMock(spec=SQLAlchemyUnitOfWork)
    uow.commit.side_effect = RuntimeError("failed commit")
    service = MarketSyncService(FakeRepository(), FakeGateway(), uow)
    with pytest.raises(RuntimeError, match="failed commit"):
        await service.sync("jita")
    uow.rollback.assert_awaited_once()


async def test_empty_hub_snapshot_is_saved_and_skipped_until_expiry() -> None:
    repository = FakeRepository()
    await repository.replace(state("amarr"), [price(hub_id="amarr")])
    gateway = FakeGateway()
    service = MarketSyncService(
        repository, gateway, AsyncMock(spec=SQLAlchemyUnitOfWork), lambda: NOW
    )
    report = await service.sync("amarr")
    assert report.items == 0
    assert gateway.calls == [(10000043, 1), (10000043, 2)]
    assert repository.prices["amarr"] == []
    assert (await service.sync_if_stale("amarr")).skipped


async def test_expired_hub_is_refreshed() -> None:
    repository, gateway = FakeRepository(), FakeGateway()
    await repository.replace(state(), [price()])
    service = MarketSyncService(
        repository,
        gateway,
        AsyncMock(spec=SQLAlchemyUnitOfWork),
        lambda: EXPIRES,
    )
    assert not (await service.sync_if_stale("jita")).skipped
    assert len(gateway.calls) == 2


@pytest.fixture
async def session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with AsyncSession(engine, expire_on_commit=False) as session:
        yield session
    await engine.dispose()


async def test_snapshot_replacement_hub_isolation_and_rollback(session: AsyncSession) -> None:
    repository = SQLMarketRepository(session)
    assert await repository.state("jita") is None
    await repository.replace(state(), [price()])
    await repository.replace(state("amarr"), [price(hub_id="amarr")])
    await session.commit()
    assert await repository.state("jita") == state()
    await repository.replace(state(items=205), [price(number) for number in range(205)])
    await session.commit()
    assert await repository.count(PriceQuery(), NOW) == 205
    await repository.replace(state(items=0), [])
    assert await repository.count(PriceQuery(), NOW) == 0
    assert await repository.count(PriceQuery(hub_id="amarr"), NOW) == 1
    await session.rollback()
    assert await repository.count(PriceQuery(), NOW) == 205
    with pytest.raises(ValueError, match="different hub"):
        await repository.replace(state(), [price(hub_id="amarr")])


@pytest.mark.parametrize(
    ("kwargs", "ids"),
    [
        ({}, [10, 20]),
        ({"type_ids": [10]}, [10]),
        ({"type_ids": []}, []),
        ({"exclude_type_ids": [10]}, [20]),
        ({"has_buy": True}, [10]),
        ({"has_buy": False}, [20]),
        ({"has_sell": False}, []),
        ({"has_sell": True}, [10, 20]),
        ({"min_buy_price": "9", "max_buy_price": "10"}, [10]),
        ({"max_sell_price": "15"}, [10]),
        ({"min_sell_price": "15"}, [20]),
        ({"min_spread": "0", "max_spread": "2"}, [10]),
        ({"min_buy_volume": 1}, [10]),
        ({"min_sell_volume": 30}, [20]),
        ({"fresh_only": True}, [10]),
        ({"offset": 1, "limit": 1}, [20]),
    ],
)
async def test_price_filters(session: AsyncSession, kwargs: dict[str, Any], ids: list[int]) -> None:
    repository = SQLMarketRepository(session)
    await repository.replace(
        state(items=2),
        [
            price(),
            price(
                20,
                buy_price=None,
                buy_volume=0,
                sell_price="20",
                sell_volume=40,
                spread=None,
                expires_at=NOW - timedelta(seconds=1),
                synced_at=NOW - timedelta(minutes=20),
            ),
        ],
    )
    query = PriceQuery.model_validate(kwargs)
    assert [entry.type_id for entry in await repository.find(query, NOW)] == ids
    expected_count = 2 if kwargs.get("offset") else len(ids)
    assert await repository.count(query, NOW) == expected_count


@pytest.mark.parametrize(
    "kwargs",
    [
        {"min_buy_price": 10, "max_buy_price": 1},
        {"min_sell_price": 10, "max_sell_price": 1},
        {"min_spread": 10, "max_spread": 1},
    ],
)
def test_inverted_ranges_rejected(kwargs: dict[str, Any]) -> None:
    with pytest.raises(ValueError, match="Minimum"):
        PriceQuery.model_validate(kwargs)


async def test_api_hub_selection_and_validation() -> None:
    repository = FakeRepository()
    await repository.replace(state("amarr"), [price(hub_id="amarr")])
    provider = Provider(scope=Scope.REQUEST)
    provider.provide(lambda: MarketService(repository), provides=MarketService)
    container = make_async_container(provider)
    app = create_app(container=container, settings=make_settings(), require_login=False)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://test"
    ) as client:
        assert len((await client.get("/api/v1/market/hubs")).json()) == 5
        response = await client.get("/api/v1/market/prices?hub_id=amarr")
        assert response.status_code == 200, response.text
        assert response.json()["items"][0]["hub_id"] == "amarr"
        assert (await client.get("/api/v1/market/prices")).json()["items"] == []
        assert (await client.get("/api/v1/market/prices?hub_id=invalid")).status_code == 422
    await container.close()


@pytest.mark.parametrize("expires", ["Mon, 16 Nov 2026 00:01:00 GMT", "invalid", None])
async def test_gateway_pagination_expiry_and_decimal(expires: str | None) -> None:
    async with httpx.AsyncClient(base_url="https://test") as http:
        gateway = EsiMarketGateway(EsiClient(http, 1, 0, lambda: "2026-11-16"), clock=lambda: NOW)
        headers = {"X-Pages": "3"}
        if expires:
            headers["Expires"] = expires
        with respx.mock:
            route = respx.get("https://test/markets/10000002/orders/").respond(
                200,
                headers=headers,
                text='[{"order_id":1,"type_id":10,"location_id":60003760,'
                '"is_buy_order":false,"price":10.10,"volume_remain":5}]',
            )
            batch = await gateway.get_orders(10000002, 2)
            assert batch.pages == 3
            assert batch.orders[0].price == Decimal("10.10")
            assert route.calls[0].request.url.params["page"] == "2"
            assert batch.expires_at == (
                NOW + timedelta(minutes=1) if expires and expires != "invalid" else EXPIRES
            )


async def test_pagination_drift_restarts_without_mixing_snapshots() -> None:
    gateway = FakeGateway()
    original = gateway.get_orders
    calls = 0

    async def changing(region_id: int, page: int) -> OrderPage:
        nonlocal calls
        calls += 1
        batch = await original(region_id, page)
        if calls == 2:
            batch.pages = 3
        return batch

    gateway.get_orders = changing  # type: ignore[method-assign]
    repository = FakeRepository()
    uow = AsyncMock(spec=SQLAlchemyUnitOfWork)
    report = await MarketSyncService(repository, gateway, uow, lambda: NOW).sync("jita")
    assert calls == 4
    assert report.pages == 2
    assert repository.prices["jita"][0].sell_volume == 5
    uow.commit.assert_awaited_once()


async def test_buy_levels_aggregate_and_round_trip_without_raw_orders(
    session: AsyncSession,
) -> None:
    aggregator = PriceAggregator(get_hub("jita"), NOW, EXPIRES)
    for entry in [
        order(is_buy_order=True, price="95", volume_remain=40),
        order(is_buy_order=True, price="100", volume_remain=1),
        order(is_buy_order=True, price="95", volume_remain=60),
        order(is_buy_order=True, price="94.99", volume_remain=200),
        order(is_buy_order=True, price="10000", volume_remain=999, location_id=123),
    ]:
        aggregator.add(entry)
    result = aggregator.finish(EXPIRES)[0]
    assert result.buy_price == 100
    assert result.buy_volume == 1
    assert result.buy_levels is not None
    assert [(v.price, v.volume, v.order_count) for v in result.buy_levels] == [
        (Decimal(100), 1, 1),
        (Decimal(95), 100, 2),
        (Decimal("94.99"), 200, 1),
    ]
    repository = SQLMarketRepository(session)
    await repository.replace(state(), [result])
    await session.commit()
    stored = (await repository.find(PriceQuery(), NOW))[0]
    assert stored.buy_levels == result.buy_levels
    assert stored.buy_volume == result.buy_volume
