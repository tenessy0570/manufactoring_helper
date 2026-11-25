from decimal import Decimal

from app.domains.invention.gateway import InventionResponse
from app.domains.manufacturing.gateway import parse_duration_seconds
from app.domains.manufacturing.models import ManufacturingQuery


def test_invention_time_slots_default_and_duration_per_attempt() -> None:
    assert ManufacturingQuery().invention_slots == 1
    assert not ManufacturingQuery().include_invention_time
    assert ManufacturingQuery.model_validate({"invention_slots": ""}).invention_slots == 1
    response = InventionResponse.model_validate(
        {
            "product_id": 1,
            "blueprint_id": 2,
            "probability": "0.5",
            "runs": "0.2",
            "runs_per_copy": 10,
            "units_per_run": 1,
            "materials": {},
            "total_job_cost": 0,
            "me": 0,
            "te": 0,
            "time": "PT20M",
        }
    )
    assert response.time is not None
    assert parse_duration_seconds(response.time) / response.runs == 6000


def test_parallel_invention_and_production_and_copy_rounding() -> None:
    from app.domains.manufacturing.demand import calculate_invention_daily_profit

    # 11 runs need 2 copies: at 50% chance, 4 attempts.
    profit = Decimal(1000)
    one = calculate_invention_daily_profit(
        profit, 11, Decimal(10000), 10, Decimal("0.5"), Decimal(10000), 1, 1
    )
    two = calculate_invention_daily_profit(
        profit, 11, Decimal(10000), 10, Decimal("0.5"), Decimal(10000), 1, 2
    )
    assert one == profit * (Decimal(86400) / 150000)
    assert two > one
    assert (
        calculate_invention_daily_profit(
            profit, 11, Decimal(10000), 10, Decimal("0.5"), Decimal(10000), 2, 2
        )
        == profit
    )


def test_short_batch_invention_slowdown_not_erased_by_daily_cap() -> None:
    from app.domains.manufacturing.demand import calculate_invention_daily_profit

    args = (Decimal(1000), 10, Decimal(100), 10, Decimal("0.5"))
    with_time = calculate_invention_daily_profit(*args, Decimal(1000), 10, 10, cap_to_day=False)
    without_time = calculate_invention_daily_profit(*args, Decimal(0), 10, 10, cap_to_day=False)
    assert abs(with_time / without_time - Decimal(1) / 11) < Decimal("1e-25")
    assert with_time < without_time


def test_copying_covers_failed_attempts_and_adds_sequential_time() -> None:
    from app.domains.manufacturing.demand import calculate_invention_daily_profit

    original = calculate_invention_daily_profit(
        Decimal(1000), 10, Decimal(3600), 10, Decimal("0.5"), Decimal(3600), 1, 1, cap_to_day=False
    )
    copying = calculate_invention_daily_profit(
        Decimal(1000), 10, Decimal(3600), 10, Decimal("0.5"), Decimal(5400), 1, 1, cap_to_day=False
    )
    assert original == 2000
    assert copying == Decimal(1000) * (Decimal(86400) / 46800)
    assert copying < original
