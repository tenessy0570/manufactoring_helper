import logging
import math
from abc import ABC, abstractmethod

from pydantic import JsonValue, TypeAdapter

from app.core.cache import Cache, CacheService
from app.domains.market.models import HubId
from app.domains.trading.models import RouteMode, TradeRoute
from app.infrastructure.esi import EsiClient

logger = logging.getLogger(__name__)
SYSTEMS: dict[HubId, int] = {
    "jita": 30000142,
    "amarr": 30002187,
    "dodixie": 30002659,
    "rens": 30002510,
    "hek": 30002053,
}
PATH = TypeAdapter(list[int])


class RouteGateway(ABC):
    @abstractmethod
    async def path(self, origin: int, destination: int, mode: RouteMode) -> list[int]: ...

    @abstractmethod
    async def security(self, system: int) -> float: ...


class EsiRouteGateway(RouteGateway):
    def __init__(self, esi: EsiClient) -> None:
        self._esi = esi

    async def path(self, origin: int, destination: int, mode: RouteMode) -> list[int]:
        data = await self._esi.post_json(
            f"/route/{origin}/{destination}",
            {"preference": "Safer" if mode == "safe" else "Shorter", "security_penalty": 100},
        )
        return PATH.validate_python(data["route"])

    async def security(self, system: int) -> float:
        data = await self._esi.get_json(f"/v4/universe/systems/{system}/")
        return float(data["security_status"])


class TradingRoutes:
    def __init__(self, cache: Cache, loader: CacheService, gateway: RouteGateway) -> None:
        self._cache, self._loader, self._gateway = cache, loader, gateway

    @staticmethod
    def key(source: HubId, destination: HubId, mode: RouteMode) -> str:
        return f"trade:route:v1:{source}:{destination}:{mode}"

    async def cached(self, source: HubId, destination: HubId, mode: RouteMode) -> TradeRoute:
        data = await self._cache.get(self.key(source, destination, mode))
        return TradeRoute.model_validate(data) if data is not None else TradeRoute()

    async def refresh(self, source: HubId, destination: HubId, mode: RouteMode) -> None:
        key = self.key(source, destination, mode)
        if await self._cache.get(key) is not None:
            return
        try:
            route = await self._gateway.path(SYSTEMS[source], SYSTEMS[destination], mode)
            if (
                len(route) < 2
                or route[0] != SYSTEMS[source]
                or route[-1] != SYSTEMS[destination]
                or len(set(route)) != len(route)
            ):
                raise ValueError("Invalid route endpoints or repeated systems")
            highsec = True
            for system in route:

                async def load_security(system: int = system) -> JsonValue:
                    return await self._gateway.security(system)

                security = await self._loader.get_or_load(
                    f"trade:security:v1:{system}", load_security, 86400
                )
                # EVE displays security rounded to one decimal: 0.45 is displayed as 0.5.
                if (
                    not isinstance(security, (int, float))
                    or not math.isfinite(security)
                    or security < 0.45
                ):
                    highsec = False
            result = TradeRoute(jumps=len(route) - 1, highsec=highsec)
            if mode == "safe" and not highsec:
                result = TradeRoute(error="No verified high-sec route")
            await self._cache.set(key, result.model_dump(mode="json"), 86400)
        except Exception:
            logger.exception("Route refresh failed: %s to %s (%s)", source, destination, mode)
            await self._cache.set(
                key, TradeRoute(error="Route temporarily unavailable").model_dump(mode="json"), 300
            )
