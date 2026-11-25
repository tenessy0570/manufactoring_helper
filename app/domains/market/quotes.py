from abc import ABC, abstractmethod
from collections.abc import Sequence
from datetime import UTC

from pydantic import TypeAdapter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.market.models import HubId, MarketPrice
from app.domains.market.tables import MarketPriceTable

_PRICES = TypeAdapter(list[MarketPrice])


class MarketQuoteReader(ABC):
    @abstractmethod
    async def get_quotes(
        self, hub_id: HubId, type_ids: Sequence[int], *, include_sell_levels: bool = True
    ) -> dict[int, MarketPrice]: ...


class SQLMarketQuoteReader(MarketQuoteReader):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_quotes(
        self, hub_id: HubId, type_ids: Sequence[int], *, include_sell_levels: bool = True
    ) -> dict[int, MarketPrice]:
        quotes_by_type_id: dict[int, MarketPrice] = {}
        columns = [
            column
            for column in MarketPriceTable.__table__.c
            if include_sell_levels or column.name != "sell_levels"
        ]
        for start in range(0, len(type_ids), 500):
            rows = await self._session.execute(
                select(*columns).where(
                    MarketPriceTable.hub_id == hub_id,
                    MarketPriceTable.type_id.in_(type_ids[start : start + 500]),
                )
            )
            for quote in _PRICES.validate_python(rows.mappings().all()):
                quote.expires_at = (
                    quote.expires_at.replace(tzinfo=UTC)
                    if quote.expires_at.tzinfo is None
                    else quote.expires_at
                )
                quotes_by_type_id[quote.type_id] = quote
        return quotes_by_type_id
