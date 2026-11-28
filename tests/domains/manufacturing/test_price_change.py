from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.history.models import LiquidityQuery
from app.domains.history.repository import SQLHistoryRepository
from app.domains.manufacturing.models import ManufacturingQuery
from app.domains.manufacturing.service import ManufacturingService
from tests.domains.catalog.test_catalog import NOW
from tests.domains.history.test_history import day, get_state
from tests.domains.manufacturing.test_manufacturing import seed
from tests.domains.manufacturing.test_manufacturing import session as session


@pytest.mark.parametrize(("prices", "expected"), [([10, 20, 1000], 20), ([10, 20, 30, 1000], 25)])
async def test_median_uses_completed_traded_days_in_selected_region_and_window(
    session: AsyncSession, prices: list[int], expected: int
) -> None:
    repository = SQLHistoryRepository(session)
    await repository.replace(
        get_state(),
        [
            *[day(i + 1, average=value) for i, value in enumerate(prices)],
            day(0, average=99999),
            day(31, average=99999),
            day(10, average=99999, volume=0),
            day(11, average=0),
        ],
    )
    await repository.replace(get_state(region=10000043), [day(average=99999)])
    result = await repository.get_median_prices(LiquidityQuery(type_ids=[10], days=30), NOW)
    assert result == {10: Decimal(expected)}
    assert await repository.get_median_prices(LiquidityQuery(type_ids=[999]), NOW) == {}


async def test_quote_change_and_optional_limit_use_selected_sale_side(
    session: AsyncSession,
) -> None:
    repository = await seed(session)
    history = SQLHistoryRepository(session)
    await history.replace(
        get_state(), [day(1, average=10), day(2, average=20), day(3, average=1000)]
    )
    service = ManufacturingService(repository, history, lambda: NOW)
    query = ManufacturingQuery(type_ids=[10, 20])
    page = await service.get_opportunities(query)
    item = next(item for item in page.items if item.type_id == 10)
    assert item.historical_median_price == 20
    assert item.price_change_pct == 50
    assert next(item for item in page.items if item.type_id == 20).price_change_pct is None
    assert (
        await service.get_opportunities(
            query.model_copy(update={"max_price_increase_pct": Decimal(49)})
        )
    ).total == 0
    allowed = await service.get_opportunities(
        query.model_copy(update={"max_price_increase_pct": Decimal(50)})
    )
    assert [item.type_id for item in allowed.items] == [10]
    buy = await service.get_opportunities(
        ManufacturingQuery(type_ids=[10], product_order_type="buy")
    )
    assert buy.items[0].price_change_pct == Decimal("-54.5")
