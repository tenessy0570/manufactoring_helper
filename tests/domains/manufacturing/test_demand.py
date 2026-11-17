from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.domains.manufacturing.calculation import calculate
from app.domains.manufacturing.demand import estimate_buy_demand
from app.domains.manufacturing.models import CalculationInput, ManufacturingQuery
from app.domains.market.models import BuyPriceLevel
from app.domains.profiles.models import ProfileSettings
from tests.domains.manufacturing.test_manufacturing import recipe
from tests.domains.market.test_market import price


@pytest.mark.parametrize(
    ("tolerance", "volume", "profit"), [(0, 1, "10"), (5, 101, "510"), (100, 301, "1508")]
)
def test_price_band_uses_actual_prices_and_includes_boundary(
    tolerance: int, volume: int, profit: str
) -> None:
    quote = price(
        buy_price="100",
        buy_volume=1,
        buy_levels=[
            BuyPriceLevel(price=Decimal("94.99"), volume=200, order_count=20),
            BuyPriceLevel(price=Decimal(100), volume=1, order_count=1),
            BuyPriceLevel(price=Decimal(95), volume=100, order_count=10),
        ],
    )
    query = ManufacturingQuery(
        product_order_type="buy", buy_demand_tolerance_pct=Decimal(tolerance)
    )
    calculated = calculate(
        CalculationInput(
            recipe=recipe(units=1, job_cost="0", materials=[{"type_id": 34, "quantity": 1}]),
            quotes={34: price(34, sell_price="90")},
            product_quote=quote,
        ),
        query,
    )
    assert calculated is not None
    demand = estimate_buy_demand(quote, calculated, query)
    assert demand.volume == volume
    assert demand.profit == Decimal(profit)
    assert demand.depth_available


def test_full_runs_tax_daily_throughput_and_legacy_snapshot() -> None:
    quote = price(
        buy_price="100",
        buy_volume=1,
        buy_order_count=11,
        buy_levels=[
            BuyPriceLevel(price=Decimal(100), volume=1, order_count=1),
            BuyPriceLevel(price=Decimal(95), volume=100, order_count=10),
        ],
    )
    query = ManufacturingQuery(product_order_type="buy", sales_tax=Decimal(10))
    calculated = calculate(
        CalculationInput(
            recipe=recipe(
                units=10, seconds="86400", job_cost="0", materials=[{"type_id": 34, "quantity": 10}]
            ),
            quotes={34: price(34, sell_price="90")},
            product_quote=quote,
        ),
        query,
    )
    assert calculated is not None
    demand = estimate_buy_demand(quote, calculated, query)
    assert demand.units == 100
    assert demand.full_runs == 10
    assert demand.order_count == 11
    assert demand.profit == Decimal("-445.5")
    assert demand.daily_profit == Decimal("-40.5")
    assert demand.average_price == Decimal("95.05")
    quote.buy_levels = None
    legacy = estimate_buy_demand(quote, calculated, query)
    assert not legacy.depth_available
    assert legacy.volume == 1
    assert legacy.units == 0
    assert legacy.profit == 0
    assert legacy.average_price is None
    quote.buy_price = None
    with pytest.raises(ValueError, match="buy price"):
        estimate_buy_demand(quote, calculated, query)


@pytest.mark.parametrize("value", [None, "", "0", "5.25", "100"])
def test_threshold_defaults_and_profile_persistence(value: str | None) -> None:
    expected = Decimal(5) if value in (None, "") else Decimal(value)
    profile = ProfileSettings.model_validate({"buy_demand_tolerance_pct": value})
    assert profile.buy_demand_tolerance_pct == expected
    assert ProfileSettings.model_validate_json(profile.model_dump_json()) == profile


@pytest.mark.parametrize("value", ["-1", "100.01", "NaN", "Infinity"])
def test_invalid_thresholds_are_rejected(value: str) -> None:
    with pytest.raises(ValidationError):
        ManufacturingQuery.model_validate({"buy_demand_tolerance_pct": value})
