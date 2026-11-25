from unittest.mock import AsyncMock

import pytest

from app.core.cache import CacheService, MemoryCache
from app.domains.trading.models import RouteMode, TradeRoute, TradingQuery
from app.domains.trading.routes import SYSTEMS, EsiRouteGateway, RouteGateway, TradingRoutes
from app.domains.trading.service import TradingService
from app.infrastructure.esi import EsiClient
from tests.domains.catalog.test_catalog import NOW
from tests.domains.trading.test_trading import FakeTradingRepository, trade


@pytest.mark.parametrize(
    ("mode", "security", "expected"),
    [("safe", 0.45, 2), ("safe", 0.44, None), ("shortest", -0.5, 2)],
)
async def test_route_security_and_shared_cache(
    mode: RouteMode, security: float, expected: int | None
) -> None:
    cache = MemoryCache(100)
    gateway = AsyncMock(spec=RouteGateway)
    gateway.get_route.return_value = [SYSTEMS["jita"], 7, SYSTEMS["amarr"]]
    gateway.get_security_status.return_value = security
    service = TradingRoutes(cache, CacheService(cache), gateway)
    assert (await service.get_cached_route("jita", "amarr", mode)).jumps is None
    await service.refresh("jita", "amarr", mode)
    result = await service.get_cached_route("jita", "amarr", mode)
    assert result.jumps == expected
    assert bool(result.error) == (expected is None)
    await service.refresh("jita", "amarr", mode)
    assert gateway.get_route.await_count == 1
    assert gateway.get_security_status.await_count == 3
    assert (await service.get_cached_route("amarr", "jita", mode)).jumps is None
    await service.refresh("amarr", "jita", mode)
    assert (await service.get_cached_route("amarr", "jita", mode)).error
    assert gateway.get_security_status.await_count == 3


@pytest.mark.parametrize("path", [[], [1, 2], [SYSTEMS["jita"], 7, 7, SYSTEMS["amarr"]]])
async def test_invalid_route_cooldown(path: list[int]) -> None:
    seconds = [0.0]
    cache = MemoryCache(100, clock=lambda: seconds[0])
    gateway = AsyncMock(spec=RouteGateway)
    gateway.get_route.return_value = path
    routes = TradingRoutes(cache, CacheService(cache), gateway)
    await routes.refresh("jita", "amarr", "safe")
    assert (await routes.get_cached_route("jita", "amarr", "safe")).jumps is None
    await routes.refresh("jita", "amarr", "safe")
    assert gateway.get_route.await_count == 1
    seconds[0] = 301
    gateway.get_route.side_effect = ConnectionError("offline")
    await routes.refresh("jita", "amarr", "safe")
    assert gateway.get_route.await_count == 2


async def test_gateway_uses_public_post_and_versioned_system_endpoint() -> None:
    esi = AsyncMock(spec=EsiClient)
    esi.post_json.return_value = {"route": [1, 2]}
    esi.get_json.return_value = {"security_status": 0.8}
    gateway = EsiRouteGateway(esi)
    assert await gateway.get_route(1, 2, "safe") == [1, 2]
    assert esi.post_json.call_args.args == (
        "/route/1/2",
        {"preference": "Safer", "security_penalty": 100},
    )
    await gateway.get_route(1, 2, "shortest")
    assert esi.post_json.call_args.args[1]["preference"] == "Shorter"
    assert await gateway.get_security_status(1) == 0.8
    esi.get_json.assert_awaited_once_with("/v4/universe/systems/1/")


async def test_trade_route_batch_profit_filters_and_cache_only() -> None:
    repo = FakeTradingRepository()
    routes = AsyncMock(spec=TradingRoutes)
    routes.get_cached_route.return_value = TradeRoute(jumps=5, highsec=True)
    service = TradingService(repo, clock=lambda: NOW, routes=routes)
    page = await service.get_opportunities(TradingQuery(rank_by="profit_per_jump"))
    assert page.items[0].profit_per_jump == 91
    assert page.items[0].jumps == 5
    routes.refresh.assert_not_awaited()
    assert not (await service.get_opportunities(TradingQuery(max_jumps=4))).items
    assert not (await service.get_opportunities(TradingQuery(min_profit_per_jump=92))).items
    assert (
        await service.get_opportunities(
            TradingQuery(max_jumps=5, min_profit_per_jump=91, rank_by="jumps")
        )
    ).items
    repo.values = [trade()]
    page = await service.get_opportunities(TradingQuery(purchase_side="buy"))
    assert page.items[0].profit_per_jump is None
    routes.get_cached_route.return_value = TradeRoute()
    page = await service.get_opportunities(TradingQuery())
    assert page.missing_routes == 1
    assert not page.items


async def test_route_worker_refreshes_all_directed_routes() -> None:
    from app.workers.trading import refresh_trade_routes

    routes = AsyncMock(spec=TradingRoutes)
    container = AsyncMock()
    container.get.return_value = routes
    await refresh_trade_routes({"container": container})
    assert routes.refresh.await_count == 40
    assert len({call.args for call in routes.refresh.await_args_list}) == 40
