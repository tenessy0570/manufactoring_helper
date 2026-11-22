from decimal import Decimal
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from app.domains.market.models import BuyPriceLevel
from app.domains.trading.cargo import CargoService, optimize, segments
from app.domains.trading.models import CargoQuery, TradeRoute
from app.domains.trading.routes import TradingRoutes
from tests.domains.trading.test_trading import FakeTradingRepository, trade


def test_optimizer_beats_density_greedy_and_budget() -> None:
    a = trade(volume_m3=Decimal(6))
    a.source.sell_price = Decimal(10)
    a.source.sell_volume = 10
    a.destination.buy_price = Decimal(22)
    a.destination.buy_levels = [BuyPriceLevel(price=Decimal(22), volume=10)]
    b = trade(volume_m3=Decimal(5), name="Second")
    b.source.type_id = b.destination.type_id = 43
    b.source.sell_price = Decimal(10)
    b.source.sell_volume = 10
    b.destination.buy_price = Decimal(19)
    b.destination.buy_levels = [BuyPriceLevel(price=Decimal(19), volume=10)]
    lines, optimal = optimize([a, b], CargoQuery(source_hub="jita", cargo_m3=Decimal(10)))
    assert optimal
    assert len(lines) == 1
    assert lines[0].type_id == 43
    assert lines[0].quantity == 2
    assert lines[0].profit == 18
    lines, _ = optimize(
        [a, b], CargoQuery(source_hub="jita", cargo_m3=Decimal(10), budget=Decimal(10))
    )
    assert lines[0].type_id == 42
    assert lines[0].quantity == 1
    assert optimize([], CargoQuery(source_hub="jita", cargo_m3=Decimal(10))) == ([], True)


def test_segments_depth_tax_range_and_marginal_profit() -> None:
    data = trade()
    data.source.sell_levels = [
        BuyPriceLevel(price=Decimal(100), volume=2),
        BuyPriceLevel(price=Decimal(105), volume=10),
    ]
    data.destination.buy_levels = [
        BuyPriceLevel(price=Decimal(150), volume=1),
        BuyPriceLevel(price=Decimal(104), volume=10),
    ]
    query = CargoQuery(source_hub="jita", cargo_m3=Decimal(100), buy_price_range=Decimal(100))
    assert segments(data, query) == [
        (1, Decimal(100), Decimal(150)),
        (1, Decimal(100), Decimal(104)),
    ]
    assert not segments(data, query.model_copy(update={"sales_tax": Decimal(100)}))
    data.source.sell_price = None
    assert segments(data, query) == []
    with pytest.raises(ValidationError):
        CargoQuery(source_hub="jita", destination_hub="jita", cargo_m3=Decimal(1))


async def test_cargo_one_destination_at_a_time_and_missing_routes() -> None:
    repo = FakeTradingRepository()
    routes = AsyncMock(spec=TradingRoutes)
    routes.cached.return_value = TradeRoute(jumps=34, highsec=True)
    service = CargoService(repo, routes)
    query = CargoQuery(source_hub="jita", cargo_m3=Decimal(20))
    page = await service.plan(query)
    assert len(page.plans) == 4
    assert page.plans[0].destination_hub == "amarr"
    assert page.plans[0].profit == 455
    assert page.plans[0].cargo_m3 <= query.cargo_m3
    assert page.partial_depth
    repo.values.append(trade(volume_m3=None))
    assert (await service.plan(query)).missing_volume == 1
    routes.cached.return_value = TradeRoute()
    assert (await service.plan(query)).skipped_routes == 4


async def test_optimizer_timeout_fallback_exact_limits(monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace

    import scipy.optimize  # type: ignore[import-untyped]

    monkeypatch.setattr(scipy.optimize, "milp", lambda **kwargs: SimpleNamespace(x=None, status=1))
    query = CargoQuery(source_hub="jita", cargo_m3=Decimal(5), budget=Decimal(150))
    lines, optimal = optimize([trade()], query)
    assert not optimal
    assert query.budget is not None
    assert sum(v.investment for v in lines) <= query.budget
    assert sum(v.cargo_m3 for v in lines) <= query.cargo_m3
    assert lines[0].quantity == 1
    data = trade(volume_m3=Decimal(100))
    assert optimize([data], query) == ([], True)


async def test_cargo_sell_scenario_and_margin() -> None:
    repo = FakeTradingRepository()
    repo.values[0].destination.buy_price = None
    routes = AsyncMock(spec=TradingRoutes)
    routes.cached.return_value = TradeRoute(jumps=34, highsec=True)
    page = await CargoService(repo, routes).plan(
        CargoQuery(
            source_hub="jita", destination_hub="amarr", cargo_m3=Decimal(20), sale_side="sell"
        )
    )
    assert page.plans[0].profit == 600
    assert page.plans[0].margin_pct == 60


async def test_cargo_excludes_ship_skins_before_optimization() -> None:
    repo = FakeTradingRepository()
    repo.values = [trade(name="Rifter Copper SKIN"), trade(name="Test skin (Permanent)")]
    routes = AsyncMock(spec=TradingRoutes)
    routes.cached.return_value = TradeRoute(jumps=34, highsec=True)
    result = await CargoService(repo, routes).plan(
        CargoQuery(source_hub="jita", destination_hub="amarr", cargo_m3=Decimal(100))
    )
    assert result.plans[0].items == []
    assert result.plans[0].profit == 0


async def test_cargo_turnover_toggle_and_destination_threshold() -> None:
    from app.domains.trading.models import TradeTurnover
    from tests.domains.catalog.test_catalog import NOW

    repo = FakeTradingRepository()
    routes = AsyncMock(spec=TradingRoutes)
    routes.cached.return_value = TradeRoute(jumps=34, highsec=True)
    service = CargoService(repo, routes)
    query = CargoQuery(
        source_hub="jita",
        destination_hub="amarr",
        cargo_m3=Decimal(20),
        min_daily_isk_volume=Decimal(100),
    )
    assert (await service.plan(query)).plans[0].items
    query.filter_daily_turnover = True
    assert not (await service.plan(query)).plans[0].items
    repo.history[(10000043, 42)] = TradeTurnover(
        type_id=42, region_id=10000043, daily_isk_volume=Decimal(100), updated_at=NOW
    )
    assert (await service.plan(query)).plans[0].items
    query.min_daily_isk_volume = Decimal(101)
    assert not (await service.plan(query)).plans[0].items
