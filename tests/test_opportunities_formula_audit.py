from decimal import Decimal

import pytest

from app.domains.manufacturing.calculation import calculate
from app.domains.manufacturing.demand import estimate_buy_demand, invention_daily_profit
from app.domains.manufacturing.models import ManufacturingQuery
from app.domains.market.models import BuyPriceLevel
from tests.domains.manufacturing.test_manufacturing import calculation_input


@pytest.mark.parametrize(
    ("materials", "product", "cost", "profit"),
    [
        ("buy", "sell", "18.6", "9.6"),
        ("buy", "buy", "18.6", "5.4"),
        ("sell", "sell", "23.5", "4.7"),
        ("sell", "buy", "23.5", "0.5"),
    ],
)
def test_audit_manual_financial_ledger(
    materials: str, product: str, cost: str, profit: str
) -> None:
    data = calculation_input()
    data.invention_cost_per_unit = Decimal(4)
    q = ManufacturingQuery.model_validate(
        {
            "material_order_type": materials,
            "product_order_type": product,
            "sales_tax": 4,
            "buy_broker_fee": 1,
            "sell_broker_fee": 2,
            "facility_tax": 2,
            "system_cost_index": 3,
            "production_lines": 3,
        }
    )
    result = calculate(data, q)
    assert result is not None
    assert result.total_cost_per_unit == Decimal(cost)
    assert result.profit_per_unit == Decimal(profit)
    assert result.profit_per_day == Decimal(profit) * 144


def test_audit_parallel_buy_capacity_and_actual_price_levels() -> None:
    data = calculation_input()
    data.recipe.seconds = Decimal(86400)
    data.product_quote.buy_levels = [
        BuyPriceLevel(price=Decimal(25), volume=3),
        BuyPriceLevel(price=Decimal(24), volume=7),
    ]
    q = ManufacturingQuery(product_order_type="buy", buy_demand_tolerance_pct=Decimal(10))
    result = calculate(data, q)
    assert result is not None
    one = estimate_buy_demand(data.product_quote, result, q)
    assert one.profit == 73
    assert one.daily_profit == 16
    q.production_lines = 2
    assert estimate_buy_demand(data.product_quote, result, q).daily_profit == 31
    q.production_lines = 10
    assert estimate_buy_demand(data.product_quote, result, q).daily_profit == 73


def test_audit_single_slot_expectation_does_not_round_failures_twice() -> None:
    # One copy at 60% success needs 5/3 attempts on average, not two guaranteed attempts.
    rate = invention_daily_profit(
        Decimal(1000), 1, Decimal(3600), 1, Decimal("0.6"), Decimal(3600), 1, 1, cap_to_day=False
    )
    assert abs(rate - Decimal(9000)) < Decimal("1e-20")
