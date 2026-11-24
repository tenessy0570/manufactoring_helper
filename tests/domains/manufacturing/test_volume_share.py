from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.history.repository import SQLHistoryRepository
from app.domains.manufacturing.calculation import calculate
from app.domains.manufacturing.demand import estimate_buy_demand
from app.domains.manufacturing.models import ManufacturingQuery
from app.domains.manufacturing.service import ManufacturingService
from app.domains.manufacturing.timing import calculate_timing
from tests.domains.catalog.test_catalog import NOW
from tests.domains.history.test_history import day, state
from tests.domains.invention.test_invention import plan
from tests.domains.manufacturing.test_manufacturing import calculation_input, seed
from tests.domains.manufacturing.test_manufacturing import session as session


@pytest.mark.parametrize("lines", [1, 10])
async def test_daily_capacity_compares_selected_lines_with_completed_day_regional_volume(
    session: AsyncSession, lines: int
) -> None:
    repository = await seed(session)
    service = ManufacturingService(repository, SQLHistoryRepository(session), lambda: NOW)
    result = await service.opportunities(ManufacturingQuery(type_ids=[10], production_lines=lines))
    item = result.items[0]
    assert item.daily_production_units == 48 * lines
    assert item.daily_units is not None
    assert item.daily_volume_share_pct is not None
    assert abs(item.daily_volume_share_pct - Decimal(7200 * lines)) < Decimal(".001")
    assert item.daily_volume_share_pct > 100
    missing = await service.opportunities(ManufacturingQuery(type_ids=[20]))
    assert missing.items[0].daily_volume_share_pct is None
    await SQLHistoryRepository(session).replace(state(), [day(volume=0)])
    empty = await service.opportunities(ManufacturingQuery(type_ids=[10]))
    assert empty.items[0].daily_volume_share_pct is None


@pytest.mark.parametrize("flag", ["include_invention_time", "include_copying_time"])
def test_capacity_uses_enabled_preparation_and_is_independent_of_money(flag: str) -> None:
    query = ManufacturingQuery.model_validate({"production_lines": 10, flag: True})
    data = calculation_input()
    result = calculate(data, query)
    assert result is not None
    for profit in (Decimal(0), Decimal(-10)):
        calculated = result.model_copy(
            update={"profit_per_unit": profit, "profit_per_day": profit * 480}
        )
        timing = calculate_timing(
            data.product_quote, calculated, None, query, plan(), Decimal(3600)
        )
        assert timing.daily_production_units == 160
    faster = query.model_copy(update={"invention_slots": 10})
    timing = calculate_timing(data.product_quote, result, None, faster, plan(), Decimal(3600))
    assert timing.daily_production_units == 400


def test_ammo_output_quantity_and_buy_demand_do_not_cap_capacity() -> None:
    query = ManufacturingQuery(production_lines=10, product_order_type="buy")
    data = calculation_input()
    data.recipe.units = 5000
    result = calculate(data, query)
    assert result is not None
    demand = estimate_buy_demand(data.product_quote, result, query)
    assert demand.full_runs == 0
    timing = calculate_timing(data.product_quote, result, demand, query, None, Decimal(0))
    assert timing.daily_production_units == 1200000
