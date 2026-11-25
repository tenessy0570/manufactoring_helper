from abc import ABC, abstractmethod
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from email.utils import parsedate_to_datetime

from pydantic import TypeAdapter

from app.domains.market.models import MarketOrder, OrderPage
from app.infrastructure.esi import EsiClient


class MarketGateway(ABC):
    @abstractmethod
    async def get_orders(self, region_id: int, page: int) -> OrderPage: ...


class EsiMarketGateway(MarketGateway):
    def __init__(
        self,
        esi: EsiClient,
        fallback_ttl_seconds: int = 300,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._esi = esi
        self._cache_ttl_seconds = fallback_ttl_seconds
        self._clock = clock

    async def get_orders(self, region_id: int, page: int) -> OrderPage:
        response = await self._esi.request(
            "GET", f"/markets/{region_id}/orders/", params={"order_type": "all", "page": page}
        )
        pages = int(response.headers["X-Pages"])
        expires = self._clock() + timedelta(seconds=self._cache_ttl_seconds)
        if value := response.headers.get("Expires"):
            try:
                parsed = parsedate_to_datetime(value)
                parsed = parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed
                expires = min(expires, parsed)
            except (ValueError, TypeError):
                pass
        orders = TypeAdapter(list[MarketOrder]).validate_python(response.json(parse_float=Decimal))
        return OrderPage(orders=orders, page=page, pages=pages, expires_at=expires)
