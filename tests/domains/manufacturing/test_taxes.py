from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.domains.manufacturing.calculation import calculate
from app.domains.manufacturing.demand import estimate_buy_demand
from app.domains.manufacturing.models import ManufacturingQuery
from app.domains.profiles.models import ProfileSettings
from tests.domains.manufacturing.test_manufacturing import calculation_input

RATES = {
    "buy_broker_fee": "2",
    "sell_broker_fee": "3",
    "sales_tax": "10",
    "facility_tax": "1",
    "system_cost_index": "2",
}


@pytest.mark.parametrize(
    ("material_side", "product_side", "profit"),
    [("sell", "sell", "7.6"), ("buy", "sell", "12.4"), ("sell", "buy", "4"), ("buy", "buy", "8.8")],
)
def test_independent_rates_eiv_and_scc(material_side: str, product_side: str, profit: str) -> None:
    query = ManufacturingQuery.model_validate(
        {
            **RATES,
            "material_order_type": material_side,
            "product_order_type": product_side,
        }
    )
    result = calculate(calculation_input(), query)
    assert result is not None
    assert result.estimated_item_value_per_unit == 50
    assert result.base_job_cost_per_unit == 2
    assert result.facility_tax_per_unit == Decimal("0.5")
    assert result.system_cost_per_unit == 1
    assert result.job_cost_per_unit == Decimal("3.5")
    assert result.profit_per_unit == Decimal(profit)
    assert result.margin_pct == result.profit_per_unit / result.material_cost_per_unit * 100
    assert result.profit_per_day == result.profit_per_unit * 48
    if product_side == "buy":
        quote = calculation_input().product_quote
        demand = estimate_buy_demand(quote, result, query)
        assert demand.profit == result.profit_per_unit * demand.units


@pytest.mark.parametrize("field", list(RATES))
def test_percentage_defaults_blank_limits_and_profile_roundtrip(field: str) -> None:
    assert getattr(ManufacturingQuery(), field) == 0
    for value in (None, "", "0", "0.125", "100"):
        profile = ProfileSettings.model_validate({field: value})
        assert getattr(profile, field) == Decimal(value or 0)
        assert ProfileSettings.model_validate_json(profile.model_dump_json()) == profile
    for value in ("-0.01", "100.01", "NaN", "Infinity"):
        with pytest.raises(ValidationError):
            ManufacturingQuery.model_validate({field: value})


def test_legacy_broker_profiles_and_explicit_override() -> None:
    old = ProfileSettings(broker_fee=Decimal("2.5"))
    assert old.buy_broker_fee == old.sell_broker_fee == Decimal("2.5")
    explicit = ManufacturingQuery(
        broker_fee=Decimal(5), buy_broker_fee=Decimal(0), sell_broker_fee=Decimal(3)
    )
    assert explicit.buy_broker_fee == 0
    assert explicit.sell_broker_fee == 3
    with pytest.raises(ValidationError, match="Combined"):
        ManufacturingQuery(sales_tax=Decimal(99), sell_broker_fee=Decimal(2))


def test_legacy_recipe_never_guesses_eiv_from_market_cost_or_scc() -> None:
    data = calculation_input()
    data.recipe.estimated_item_value = None
    zero = calculate(data, ManufacturingQuery())
    assert zero is not None
    assert zero.job_cost_per_unit == 2
    assert zero.facility_tax_per_unit == zero.system_cost_per_unit == 0
    assert zero.profit_per_unit == 13
    assert calculate(data, ManufacturingQuery(facility_tax=Decimal(1))) is None
    assert calculate(data, ManufacturingQuery(system_cost_index=Decimal(1))) is None


def test_base_override_does_not_cancel_entered_industry_taxes() -> None:
    result = calculate(
        calculation_input(),
        ManufacturingQuery.model_validate(
            {
                **RATES,
                "job_cost_per_run": "0",
            }
        ),
    )
    assert result is not None
    assert result.base_job_cost_per_unit == 0
    assert result.job_cost_per_unit == Decimal("1.5")
    assert result.profit_per_unit == Decimal("9.6")
