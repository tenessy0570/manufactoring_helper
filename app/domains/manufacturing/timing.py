from decimal import ROUND_CEILING, Decimal

from app.domains.invention.models import InventionPlan
from app.domains.manufacturing.demand import estimate_buy_demand, invention_daily_profit
from app.domains.manufacturing.models import (
    BuyDemandEstimate,
    ManufacturingQuery,
    OpportunityTiming,
    ProfitCalculation,
)
from app.domains.market.models import MarketPrice


def calculate_timing(
    product: MarketPrice,
    calculated: ProfitCalculation,
    demand: BuyDemandEstimate | None,
    query: ManufacturingQuery,
    invention_plan: InventionPlan | None,
    preparation_seconds: Decimal,
) -> OpportunityTiming:
    seconds_per_run = calculated.seconds / query.production_lines
    if (query.include_invention_time or query.include_copying_time) and invention_plan is not None:
        seconds_per_run += (
            preparation_seconds
            / invention_plan.probability
            / invention_plan.runs_per_copy
            / query.invention_slots
        )
    daily_production_units = Decimal(calculated.units) * 86400 / seconds_per_run
    is_buy = query.product_order_type == "buy"
    limited_daily_profit = demand.daily_profit if demand else None
    if (
        (query.include_invention_time or query.include_copying_time)
        and demand is not None
        and invention_plan is not None
        and demand.full_runs
    ):
        daily_without_invention = demand.daily_profit
        total_daily = invention_daily_profit(
            demand.profit,
            demand.full_runs,
            calculated.seconds,
            invention_plan.runs_per_copy,
            invention_plan.probability,
            preparation_seconds,
            query.production_lines,
            query.invention_slots,
            cap_to_day=False,
        )
        production_daily = invention_daily_profit(
            demand.profit,
            demand.full_runs,
            calculated.seconds,
            invention_plan.runs_per_copy,
            invention_plan.probability,
            Decimal(0),
            query.production_lines,
            query.invention_slots,
            cap_to_day=False,
        )
        if production_daily > 0 and total_daily > 0:
            slowdown = min(Decimal(1), total_daily / production_daily)
            effective = calculated.model_copy(update={"seconds": calculated.seconds / slowdown})
            limited_daily_profit = min(
                daily_without_invention,
                estimate_buy_demand(product, effective, query).daily_profit,
            )
        else:
            limited_daily_profit = daily_without_invention
    rank_daily_profit = (
        calculated.profit_per_day if limited_daily_profit is None else limited_daily_profit
    )
    if (
        (query.include_invention_time or query.include_copying_time)
        and not is_buy
        and invention_plan is not None
    ):
        expected_invention_seconds = (
            (preparation_seconds)
            / invention_plan.probability
            / invention_plan.runs_per_copy
            / query.invention_slots
        )
        production_seconds_per_run = calculated.seconds / query.production_lines
        rank_daily_profit = (
            calculated.profit_per_day
            * production_seconds_per_run
            / (production_seconds_per_run + expected_invention_seconds)
        )
    duration = None
    if demand is not None:
        duration = (Decimal(demand.full_runs) / query.production_lines).to_integral_value(
            rounding=ROUND_CEILING
        ) * calculated.seconds
        if invention_plan is not None and demand.full_runs and preparation_seconds:
            copies = (Decimal(demand.full_runs) / invention_plan.runs_per_copy).to_integral_value(
                rounding=ROUND_CEILING
            )
            attempts = copies / invention_plan.probability
            duration += max(Decimal(1), attempts / query.invention_slots) * preparation_seconds
    return OpportunityTiming(
        daily_production_units=daily_production_units,
        daily_profit=rank_daily_profit,
        demand_daily_profit=limited_daily_profit,
        duration_seconds=duration,
    )
