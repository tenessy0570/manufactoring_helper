from typing import Any
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.catalog.repository import SQLItemTypeRepository
from app.domains.history.models import LiquidityItem, LiquidityQuery
from app.domains.history.repository import HistoryRepository, SQLHistoryRepository
from app.domains.manufacturing.loading import OpportunityDataLoader
from app.domains.manufacturing.models import ManufacturingQuery
from app.domains.manufacturing.repository import ManufacturingRepository
from tests.domains.catalog.test_catalog import NOW, item
from tests.domains.history.test_history import session as session
from tests.domains.market.test_market import price


async def test_large_candidate_set_uses_one_history_query_without_count_or_pagination(
    session: AsyncSession,
) -> None:
    await SQLItemTypeRepository(session).upsert_many([item(i) for i in range(1, 1202)])
    statements: list[str] = []

    def count(
        connection: Any, cursor: Any, statement: str, parameters: Any, context: Any, many: bool
    ) -> None:
        if "market_history" in statement:
            statements.append(statement)

    engine = session.sync_session.get_bind()
    event.listen(engine, "before_cursor_execute", count)
    repository = SQLHistoryRepository(session)
    try:
        candidates = await repository.find_candidates(LiquidityQuery(limit=1, offset=999), NOW)
        assert len(candidates) == 1201
        assert len(statements) == 1
        assert "LIMIT" not in statements[0]
        assert "OFFSET" not in statements[0]
        first, total = await repository.get_liquidity(LiquidityQuery(limit=1000), NOW)
        second, _ = await repository.get_liquidity(LiquidityQuery(limit=1000, offset=1000), NOW)
        assert total == len(candidates)
        assert first + second == candidates
    finally:
        event.remove(engine, "before_cursor_execute", count)


@pytest.mark.parametrize("hub", ["jita", "amarr"])
async def test_quote_batches_keep_product_and_material_hubs_separate(hub: str) -> None:
    history = AsyncMock(spec=HistoryRepository)
    history.find_candidates.return_value = [
        LiquidityItem(
            type_id=10,
            name="Test",
            data_days=0,
            daily_isk_volume=None,
            daily_units=None,
            latest_trade_date=None,
            synced_at=None,
            expires_at=None,
        )
    ]
    repository = AsyncMock(spec=ManufacturingRepository)
    from tests.domains.manufacturing.test_manufacturing import recipe_state

    repository.get_recipes.return_value = {10: recipe_state()}

    async def get_quotes(hub_id: str, ids: list[int]) -> dict[int, Any]:
        return {i: price(i, hub_id=hub_id) for i in ids}

    repository.get_quotes.side_effect = get_quotes
    query = ManufacturingQuery.model_validate({"material_hub_id": hub})
    inputs = await OpportunityDataLoader(repository, history, None).load(query, NOW, True)
    assert inputs.quotes[34].hub_id == hub
    assert inputs.products[10].hub_id == "jita"
    assert repository.get_quotes.await_count == (1 if hub == "jita" else 2)


async def test_light_quotes_keep_buy_depth_and_prices_without_reading_sell_depth(
    session: AsyncSession,
) -> None:
    from app.domains.manufacturing.repository import SQLManufacturingRepository
    from app.domains.market.quotes import SQLMarketQuoteReader
    from app.domains.market.repository import SQLMarketRepository
    from tests.domains.market.test_market import get_state

    await SQLMarketRepository(session).replace(
        get_state(),
        [
            price(
                10,
                buy_levels=[{"price": "10", "volume": 7}],
                sell_levels=[{"price": "15", "volume": 123}],
            )
        ],
    )
    reader = SQLMarketQuoteReader(session)
    full = (await reader.get_quotes("jita", [10]))[10]
    projected = (await SQLManufacturingRepository(session, reader).get_quotes("jita", [10]))[10]
    assert full.sell_levels is not None
    assert projected.sell_levels is None
    assert projected.buy_levels == full.buy_levels
    assert projected.model_dump(exclude={"sell_levels"}) == full.model_dump(exclude={"sell_levels"})
