import runpy
from datetime import timedelta
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock

import httpx
import pytest
import respx
from alembic.migration import MigrationContext
from alembic.operations import Operations
from dishka import Provider, Scope, make_async_container
from pydantic import ValidationError
from sqlalchemy import create_engine, inspect
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core.di import create_container
from app.core.orm import Base
from app.core.repository import UnitOfWork
from app.domains.catalog.names import ItemNameService, ItemNamesUnavailableError
from app.domains.market.models import HUBS, BuyPriceLevel
from app.domains.market.repository import SQLMarketRepository
from app.domains.trading.calculation import calculate_trade
from app.domains.trading.gateway import EverefTradingGateway, TradingGateway
from app.domains.trading.models import (
    TradeInput,
    TradeMetadata,
    TradeTurnover,
    TradeTypeDetails,
    TradingQuery,
)
from app.domains.trading.repository import SQLTradingRepository, TradingRepository
from app.domains.trading.service import TradingMetadataService, TradingService
from app.infrastructure.everef import EverefClient
from app.main import create_app
from tests.domains.catalog.test_catalog import NOW
from tests.domains.market.test_market import get_state, price
from tests.helpers import make_settings


def trade(**changes: Any) -> TradeInput:
    data = TradeInput(
        source=price(42, hub_id="jita", sell_price="100", buy_price="90", sell_volume=10),
        destination=price(
            42,
            hub_id="amarr",
            buy_price="150",
            sell_price="160",
            buy_volume=5,
            buy_levels=[
                BuyPriceLevel(price=Decimal(150), volume=1),
                BuyPriceLevel(price=Decimal(145), volume=20),
            ],
        ),
        name="Example item",
        volume_m3=Decimal(2),
        metadata_expires_at=NOW + timedelta(days=7),
    )
    return data.model_copy(update=changes)


@pytest.mark.parametrize(
    ("purchase", "sale", "profit", "batch"),
    [
        ("sell", "buy", 50, 455),
        ("sell", "sell", 60, 600),
        ("buy", "buy", 60, None),
        ("buy", "sell", 70, None),
    ],
)
def test_pricing_modes_actual_depth_and_order_scenarios(
    purchase: str, sale: str, profit: int, batch: int | None
) -> None:
    result = calculate_trade(
        trade(), TradingQuery.model_validate({"purchase_side": purchase, "sale_side": sale}), NOW
    )
    assert result is not None
    assert result.profit_per_unit == profit
    assert result.batch_profit == batch
    assert result.instant_trade == (purchase == "sell" and sale == "buy")
    assert result.source_stock == (10 if purchase == "sell" else None)
    if purchase == "buy":
        assert result.quantity is None
        assert result.warnings
    if sale == "buy":
        assert result.destination_demand == 21
    if batch == 455:
        assert result.quantity == 10
        assert result.average_sale_price == Decimal("145.5")
        assert result.investment == 1000
        assert result.cargo_m3 == 20
        assert result.profit_per_m3 == Decimal("22.75")


def test_taxes_profit_density_caps_and_exact_quantity() -> None:
    result = calculate_trade(
        trade(),
        TradingQuery(sales_tax=Decimal(10), sell_broker_fee=Decimal(5)),
        NOW,
    )
    assert result is not None
    assert result.cost_per_unit == 100
    assert result.profit_per_unit == 35
    assert result.batch_profit == Decimal("309.5")
    assert result.profit_per_m3 == Decimal("15.475")
    assert result.sale_fee == 15
    assert result.purchase_fee == 0
    for query in [
        TradingQuery(max_investment=Decimal(201)),
        TradingQuery(max_cargo_m3=Decimal(5)),
        TradingQuery(max_units=2),
    ]:
        capped = calculate_trade(trade(), query, NOW)
        assert capped is not None
        assert capped.quantity == 2
        assert capped.batch_profit == 95
        assert capped.profit_per_m3 == Decimal("23.75")
    bought = calculate_trade(
        trade(), TradingQuery(purchase_side="buy", max_units=4, buy_broker_fee=Decimal(2)), NOW
    )
    assert bought is not None
    assert bought.quantity == 4
    assert bought.purchase_fee == Decimal("1.8")
    assert bought.batch_profit == Decimal("217.8")
    sold = calculate_trade(
        trade(),
        TradingQuery(sale_side="sell", sales_tax=Decimal(10), sell_broker_fee=Decimal(2)),
        NOW,
    )
    assert sold is not None
    assert sold.profit_per_unit == Decimal("40.8")
    zero = calculate_trade(trade(volume_m3=Decimal(0)), TradingQuery(max_cargo_m3=Decimal(1)), NOW)
    assert zero is not None
    assert zero.cargo_m3 == 0
    assert zero.profit_per_m3 is None


def test_demand_threshold_and_no_unprofitable_or_unavailable_units() -> None:
    only_best = calculate_trade(trade(), TradingQuery(buy_price_range=Decimal(0)), NOW)
    assert only_best is not None
    assert only_best.quantity == 1
    assert only_best.batch_profit == 50
    legacy = trade()
    legacy.destination.buy_levels = None
    result = calculate_trade(legacy, TradingQuery(), NOW)
    assert result is not None
    assert result.quantity == 5
    assert result.batch_profit == 250
    assert result.warnings
    poor = trade()
    poor.destination.buy_levels = [BuyPriceLevel(price=Decimal(90), volume=100)]
    assert calculate_trade(poor, TradingQuery(buy_price_range=Decimal(100)), NOW) is None
    absent = trade()
    absent.source.sell_price = None
    assert calculate_trade(absent, TradingQuery(), NOW) is None
    absent = trade()
    absent.destination.buy_price = None
    assert calculate_trade(absent, TradingQuery(), NOW) is None
    free = trade()
    free.source.sell_price = Decimal(0)
    assert calculate_trade(free, TradingQuery(), NOW) is None
    expensive = trade()
    expensive.source.sell_price = Decimal(200)
    assert calculate_trade(expensive, TradingQuery(), NOW) is None
    empty = trade()
    empty.source.sell_volume = 0
    assert calculate_trade(empty, TradingQuery(), NOW) is None
    assert calculate_trade(trade(), TradingQuery(max_investment=Decimal(1)), NOW) is None
    assert calculate_trade(trade(), TradingQuery(min_profit=Decimal(51)), NOW) is None
    assert calculate_trade(trade(), TradingQuery(min_margin=Decimal(51)), NOW) is None
    assert calculate_trade(trade(), TradingQuery(min_batch_profit=Decimal(456)), NOW) is None
    assert (
        calculate_trade(
            trade(), TradingQuery(purchase_side="buy", min_batch_profit=Decimal(0)), NOW
        )
        is None
    )


def test_missing_and_expired_metadata_and_market_freshness() -> None:
    unknown = trade(volume_m3=None, metadata_expires_at=None)
    result = calculate_trade(unknown, TradingQuery(), NOW)
    assert result is not None
    assert result.profit_per_unit == 50
    assert result.cargo_m3 is None
    assert result.warnings
    assert calculate_trade(unknown, TradingQuery(max_cargo_m3=Decimal(1)), NOW) is None
    old = trade(metadata_expires_at=NOW)
    result = calculate_trade(old, TradingQuery(), NOW)
    assert result is not None
    assert result.stale
    assert calculate_trade(old, TradingQuery(fresh_only=True), NOW) is None
    old = trade()
    old.destination.synced_at = NOW - timedelta(minutes=20)
    assert calculate_trade(old, TradingQuery(fresh_only=True), NOW) is None


@pytest.mark.parametrize(
    "values",
    [
        {"source_hub": "amarr", "destination_hub": "amarr"},
        {"sales_tax": 90, "sell_broker_fee": 11},
        {"sales_tax": -1},
        {"min_profit": "NaN"},
        {"buy_price_range": 101},
        {"max_investment": 0},
        {"limit": 101},
    ],
)
def test_query_validation(values: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        TradingQuery.model_validate(values)


class FakeTradingRepository(TradingRepository):
    def __init__(self) -> None:
        self.values = [trade()]
        self.saved: dict[int, TradeMetadata] = {}
        self.fail = False
        self.history: dict[tuple[int, int], TradeTurnover] = {}

    async def get_turnover(
        self, query: TradingQuery, type_ids: list[int], now: Any
    ) -> dict[tuple[int, int], TradeTurnover]:
        return self.history

    async def get_trade_inputs(self, query: TradingQuery) -> list[TradeInput]:
        return self.values

    async def get_market_type_ids(self) -> list[int]:
        return [42]

    async def find_due_metadata_ids(self, now: Any) -> list[int]:
        return [42]

    async def get_metadata(self, type_id: int) -> TradeMetadata | None:
        return self.saved.get(type_id)

    async def save_metadata(self, metadata: TradeMetadata) -> None:
        if self.fail:
            raise RuntimeError("write failed")
        self.saved[metadata.type_id] = metadata

    async def get_snapshot_times(self, query: TradingQuery) -> tuple[Any, Any]:
        return NOW, NOW


async def test_service_sort_search_pagination_and_name_recovery() -> None:
    repo = FakeTradingRepository()
    second = trade(name="Another item", volume_m3=None, metadata_expires_at=None)
    second.source.type_id = 43
    second.destination.type_id = 43
    repo.values.append(second)
    service = TradingService(repo, clock=lambda: NOW)
    for rank in ["batch_profit", "profit", "margin", "profit_per_m3"]:
        page = await service.get_opportunities(TradingQuery(rank_by=rank, limit=1))
        assert page.total == 2
        assert page.items[0].type_id == 42
        assert page.missing_metadata == 1
    page = await service.get_opportunities(TradingQuery(search="ANOTHER", offset=0))
    assert page.total == 1
    assert page.items[0].type_id == 43
    assert (await service.get_opportunities(TradingQuery(offset=10))).items == []
    second.name = None
    assert (await service.get_opportunities(TradingQuery(search="another"))).items == []
    names = AsyncMock(spec=ItemNameService)
    names.resolve.return_value = type("Names", (), {"names": {43: "Resolved"}})()
    resolved = await TradingService(repo, names, lambda: NOW).get_opportunities(TradingQuery())
    assert resolved.items[1].name == "Resolved"
    names.resolve.side_effect = ItemNamesUnavailableError()
    assert (
        await TradingService(repo, names, lambda: NOW).get_opportunities(TradingQuery())
    ).total == 2


@pytest.mark.parametrize("packaged", [None, Decimal("0.5")])
async def test_metadata_cache_prefers_packaged_volume_and_rolls_back(
    packaged: Decimal | None,
) -> None:
    repo = FakeTradingRepository()
    gateway = AsyncMock(spec=TradingGateway)
    unit_of_work = AsyncMock(spec=UnitOfWork)
    gateway.get_type_details.return_value = TradeTypeDetails(
        name="Ship", volume=Decimal(100), packaged_volume=packaged
    )
    service = TradingMetadataService(repo, gateway, unit_of_work, lambda: NOW)
    assert await service.sync(42)
    assert repo.saved[42].volume_m3 == (packaged if packaged is not None else 100)
    assert not await service.sync(42)
    gateway.get_type_details.assert_awaited_once_with(42)
    repo.saved[42].expires_at = NOW
    repo.fail = True
    with pytest.raises(RuntimeError, match="write failed"):
        await service.sync(42)
    unit_of_work.rollback.assert_awaited_once()


async def test_repository_all_market_items_metadata_and_snapshots() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with AsyncSession(engine) as session:
        repo = SQLTradingRepository(session)
        market = SQLMarketRepository(session)
        assert await repo.get_snapshot_times(TradingQuery()) == (None, None)
        assert await repo.get_metadata(42) is None
        await market.replace(get_state("jita"), [trade().source, price(70)])
        await market.replace(get_state("amarr"), [trade().destination])
        assert await repo.get_market_type_ids() == [42, 70]
        assert await repo.find_due_metadata_ids(NOW) == [42, 70]
        values = await repo.get_trade_inputs(
            TradingQuery(source_hub="jita", destination_hub="amarr")
        )
        assert [value.source.type_id for value in values] == [42]
        assert values[0].name is None
        await repo.save_metadata(
            TradeMetadata(
                type_id=42,
                name="Outside manufacturing catalogue",
                volume_m3=Decimal(2),
                updated_at=NOW,
                expires_at=NOW + timedelta(days=7),
            )
        )
        assert (
            await repo.get_trade_inputs(TradingQuery(source_hub="jita", destination_hub="amarr"))
        )[0].name == "Outside manufacturing catalogue"
        assert await repo.find_due_metadata_ids(NOW) == [70]
        assert await repo.find_due_metadata_ids(NOW + timedelta(days=8)) == [42, 70]
        saved = await repo.get_metadata(42)
        assert saved is not None
        assert saved.updated_at == NOW
        assert await repo.get_snapshot_times(
            TradingQuery(source_hub="jita", destination_hub="amarr")
        ) == (
            NOW,
            NOW,
        )
    await engine.dispose()


async def test_api_validation_and_provider_wiring() -> None:
    service = TradingService(FakeTradingRepository(), clock=lambda: NOW)
    provider = Provider(scope=Scope.REQUEST)
    provider.provide(lambda: service, provides=TradingService)
    container = make_async_container(provider)
    app = create_app(container, make_settings(), require_login=False)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://test"
    ) as client:
        response = await client.get("/api/v1/trading/opportunities")
        assert response.status_code == 200
        assert response.json()["items"][0]["batch_profit"] == "455"
        assert (
            await client.get("/api/v1/trading/opportunities?source_hub=jita&destination_hub=jita")
        ).status_code == 422
    await container.close()
    container = create_container(make_settings())
    async with container() as scope:
        assert isinstance(await scope.get(TradingService), TradingService)
        assert isinstance(await scope.get(TradingMetadataService), TradingMetadataService)
    await container.close()


async def test_public_gateway_reads_volume_metadata() -> None:
    async with httpx.AsyncClient(base_url="https://ref.test") as http:
        gateway = EverefTradingGateway(EverefClient(http, 1, 0))
        with respx.mock:
            respx.get("https://ref.test/types/42").respond(
                200, json={"name": {"en": "Ship"}, "volume": 100, "packaged_volume": 5}
            )
            result = await gateway.get_type_details(42)
            assert result.packaged_volume == 5
            assert result.name == "Ship"
            respx.get("https://ref.test/types/43").respond(
                200, json={"name": "Module", "volume": 2}
            )
            assert (await gateway.get_type_details(43)).name == "Module"


def test_trade_metadata_migration_roundtrip() -> None:
    migration = runpy.run_path("alembic/versions/0012_trade_metadata.py")
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection, Operations.context(MigrationContext.configure(connection)):
        migration["upgrade"]()
        assert "trade_metadata" in inspect(connection).get_table_names()
        migration["downgrade"]()
        assert "trade_metadata" not in inspect(connection).get_table_names()
    engine.dispose()


async def test_all_hubs_optional_sides_and_twenty_distinct_directions() -> None:
    query = TradingQuery()
    assert query.source_hub is None
    assert query.destination_hub is None
    assert TradingQuery.model_validate({"source_hub": "", "destination_hub": ""}) == query
    same = trade()
    same.destination.hub_id = same.source.hub_id
    assert calculate_trade(same, query, NOW) is None
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with AsyncSession(engine) as session:
        market = SQLMarketRepository(session)
        for index, hub in enumerate(HUBS):
            stamp = NOW - timedelta(minutes=index)
            await market.replace(
                get_state(hub.hub_id).model_copy(update={"synced_at": stamp}),
                [
                    price(
                        42,
                        hub_id=hub.hub_id,
                        sell_price=str(100 + index),
                        buy_price=str(150 + index),
                        sell_volume=10,
                        synced_at=stamp,
                    )
                ],
            )
        repo = SQLTradingRepository(session)
        all_pairs = await repo.get_trade_inputs(query)
        assert len(all_pairs) == 20
        assert len({(value.source.hub_id, value.destination.hub_id) for value in all_pairs}) == 20
        assert all(value.source.hub_id != value.destination.hub_id for value in all_pairs)
        assert len({id(value.source) for value in all_pairs}) == 5
        purchases = await repo.get_trade_inputs(TradingQuery(source_hub="jita"))
        assert len(purchases) == 4
        assert all(value.source.hub_id == "jita" for value in purchases)
        sales = await repo.get_trade_inputs(TradingQuery(destination_hub="jita"))
        assert len(sales) == 4
        assert all(value.destination.hub_id == "jita" for value in sales)
        assert (
            len(
                await repo.get_trade_inputs(
                    TradingQuery(source_hub="jita", destination_hub="amarr")
                )
            )
            == 1
        )
        assert await repo.get_snapshot_times(query) == (
            NOW - timedelta(minutes=4),
            NOW - timedelta(minutes=4),
        )
        service = TradingService(repo, clock=lambda: NOW)
        page = await service.get_opportunities(query)
        assert page.total == 20
        assert page.missing_metadata == 1
        assert (
            len({(item.type_id, item.source_hub, item.destination_hub) for item in page.items})
            == 20
        )
        assert page.items[0].source_hub != page.items[0].destination_hub
    await engine.dispose()


async def test_destination_turnover_filter_unknown_zero_and_expired_history() -> None:
    repo = FakeTradingRepository()
    service = TradingService(repo, clock=lambda: NOW)
    assert not TradingQuery().filter_daily_turnover
    assert (
        await service.get_opportunities(TradingQuery(min_daily_isk_volume=Decimal(1000000)))
    ).items
    unknown = await service.get_opportunities(
        TradingQuery(filter_daily_turnover=True, min_daily_isk_volume=Decimal(0))
    )
    assert unknown.items == []
    assert unknown.missing_history == 1
    repo.history[(10000043, 42)] = TradeTurnover(
        type_id=42, region_id=10000043, daily_isk_volume=Decimal(100), updated_at=NOW
    )
    repo.history[(10000002, 42)] = TradeTurnover(
        type_id=42, region_id=10000002, daily_isk_volume=Decimal(999999), updated_at=NOW
    )
    assert (
        await service.get_opportunities(
            TradingQuery(filter_daily_turnover=True, min_daily_isk_volume=Decimal(101))
        )
    ).items == []
    assert (await service.get_opportunities(TradingQuery(min_daily_isk_volume=Decimal(101)))).items
    matched = await service.get_opportunities(
        TradingQuery(filter_daily_turnover=True, min_daily_isk_volume=Decimal(100))
    )
    assert matched.items[0].daily_isk_volume == 100
    repo.history[(10000043, 42)].daily_isk_volume = Decimal(0)
    assert (
        len(
            (
                await service.get_opportunities(
                    TradingQuery(filter_daily_turnover=True, min_daily_isk_volume=Decimal(0))
                )
            ).items
        )
        == 1
    )
    repo.history[(10000043, 42)].updated_at = NOW - timedelta(days=1)
    assert (await service.get_opportunities(TradingQuery())).items[0].stale
    assert (await service.get_opportunities(TradingQuery(fresh_only=True))).items == []


async def test_daily_turnover_sql_completed_period_and_outside_catalogue() -> None:
    from app.domains.history.models import HistoryDay, HistoryState
    from app.domains.history.repository import SQLHistoryRepository

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with AsyncSession(engine) as session:
        history = SQLHistoryRepository(session)
        repo = SQLTradingRepository(session)
        for region, average in [(10000002, 1000), (10000043, 100)]:
            days = [
                HistoryDay(
                    date=NOW.date() - timedelta(days=offset),
                    average=Decimal(average),
                    highest=Decimal(average),
                    lowest=Decimal(average),
                    volume=30,
                    order_count=1,
                )
                for offset in [0, 1, 31]
            ]
            await history.replace(
                HistoryState(
                    region_id=region, type_id=42, synced_at=NOW, expires_at=NOW + timedelta(days=1)
                ),
                days,
            )
        assert await repo.get_turnover(TradingQuery(), [], NOW) == {}
        data = await repo.get_turnover(TradingQuery(history_days=30), [42, 43], NOW)
        assert data[(10000043, 42)].daily_isk_volume == 100
        assert data[(10000002, 42)].daily_isk_volume == 1000
        assert (10000043, 43) not in data
        two_days = await repo.get_turnover(
            TradingQuery(destination_hub="amarr", history_days=2), [42], NOW
        )
        assert set(two_days) == {(10000043, 42)}
        assert two_days[(10000043, 42)].daily_isk_volume == 1500
        await history.replace(
            HistoryState(
                region_id=10000043, type_id=43, synced_at=NOW, expires_at=NOW + timedelta(days=1)
            ),
            [],
        )
        empty = await repo.get_turnover(TradingQuery(), [43], NOW)
        assert empty[(10000043, 43)].daily_isk_volume == 0
    await engine.dispose()


async def test_price_spikes_default_threshold_sale_side_and_insufficient_history() -> None:
    repo = FakeTradingRepository()
    service = TradingService(repo, clock=lambda: NOW)
    assert not TradingQuery().price_spikes_only
    assert TradingQuery().price_spike_threshold == 30
    assert (await service.get_opportunities(TradingQuery())).items
    assert not (await service.get_opportunities(TradingQuery(price_spikes_only=True))).items
    record = TradeTurnover(
        type_id=42,
        region_id=10000043,
        daily_isk_volume=Decimal(100),
        updated_at=NOW,
        median_price=Decimal(100),
        baseline_days=3,
    )
    repo.history[(10000043, 42)] = record
    page = await service.get_opportunities(TradingQuery(price_spikes_only=True))
    assert page.items[0].price_spike_pct == 50
    assert page.items[0].historical_median_price == 100
    assert page.items[0].batch_profit == 455
    assert not (
        await service.get_opportunities(
            TradingQuery(price_spikes_only=True, price_spike_threshold=Decimal(51))
        )
    ).items
    sell = await service.get_opportunities(
        TradingQuery(price_spikes_only=True, sale_side="sell", price_spike_threshold=Decimal(60))
    )
    assert sell.items[0].price_spike_pct == 60
    for baseline, days in [
        (None, 7),
        (Decimal(0), 7),
        (Decimal(100), 2),
        (Decimal(150), 7),
        (Decimal(200), 7),
    ]:
        record.median_price, record.baseline_days = baseline, days
        assert not (
            await service.get_opportunities(
                TradingQuery(price_spikes_only=True, price_spike_threshold=Decimal(0))
            )
        ).items
    assert (await service.get_opportunities(TradingQuery())).items


async def test_spike_sql_seven_completed_traded_days_median_and_destination() -> None:
    from app.domains.history.models import HistoryDay, HistoryState
    from app.domains.history.repository import SQLHistoryRepository

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with AsyncSession(engine) as session:
        history = SQLHistoryRepository(session)
        repo = SQLTradingRepository(session)
        days = [
            HistoryDay(
                date=NOW.date() - timedelta(days=offset),
                average=Decimal(average),
                highest=Decimal(average),
                lowest=Decimal(average),
                volume=volume,
                order_count=1,
            )
            for offset, average, volume in [
                (0, 9999, 10),
                (1, 100, 10),
                (2, 110, 10),
                (3, 1000, 10),
                (4, 0, 10),
                (5, 900, 0),
                (7, 90, 10),
                (8, 9999, 10),
            ]
        ]
        for region in [10000043, 10000002]:
            await history.replace(
                HistoryState(
                    region_id=region, type_id=42, synced_at=NOW, expires_at=NOW + timedelta(days=1)
                ),
                days,
            )
        data = await repo.get_turnover(
            TradingQuery(price_spikes_only=True, destination_hub="amarr", history_days=1), [42], NOW
        )
        assert set(data) == {(10000043, 42)}
        assert data[(10000043, 42)].median_price == 105
        assert data[(10000043, 42)].baseline_days == 4
        assert data[(10000043, 42)].daily_isk_volume == 1000
        normal = await repo.get_turnover(TradingQuery(), [42], NOW)
        assert normal[(10000043, 42)].median_price is None
    await engine.dispose()


def test_sell_depth_actual_budget_profitability_and_range() -> None:
    data = trade()
    data.source.sell_levels = [
        BuyPriceLevel(price=Decimal(100), volume=2),
        BuyPriceLevel(price=Decimal(105), volume=10),
        BuyPriceLevel(price=Decimal(106), volume=50),
    ]
    result = calculate_trade(data, TradingQuery(), NOW)
    assert result is not None
    assert result.quantity == 12
    assert result.investment == 1250
    assert result.batch_profit == 495
    limited = calculate_trade(data, TradingQuery(max_investment=Decimal(410)), NOW)
    assert limited is not None
    assert limited.quantity == 4
    assert limited.investment == 410
    best = calculate_trade(data, TradingQuery(sell_price_range=Decimal(0)), NOW)
    assert best is not None
    assert best.quantity == 2
    data.destination.buy_levels = [
        BuyPriceLevel(price=Decimal(150), volume=1),
        BuyPriceLevel(price=Decimal(104), volume=100),
    ]
    stopped = calculate_trade(data, TradingQuery(buy_price_range=Decimal(100)), NOW)
    assert stopped is not None
    assert stopped.quantity == 2
    assert stopped.batch_profit == 54
