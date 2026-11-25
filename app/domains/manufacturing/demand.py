from decimal import ROUND_CEILING, Decimal

from app.domains.manufacturing.models import (
    BuyDemandEstimate,
    ManufacturingQuery,
    ProfitCalculation,
)
from app.domains.market.models import BuyPriceLevel, MarketPrice


def estimate_buy_demand(
    product: MarketPrice,
    calculated: ProfitCalculation,
    query: ManufacturingQuery,
    max_units: int | None = None,
) -> BuyDemandEstimate:
    best = product.buy_price
    if best is None:
        raise ValueError("Buy demand requires a buy price")
    available = product.buy_levels
    if available is None:
        available = [BuyPriceLevel(price=best, volume=product.buy_volume)]
    minimum = best * (1 - query.buy_demand_tolerance_pct / 100)
    levels = sorted(
        (level for level in available if level.price >= minimum and level.volume > 0),
        key=lambda level: level.price,
        reverse=True,
    )
    volume = sum(level.volume for level in levels)
    units = volume // calculated.units * calculated.units

    if max_units is not None:
        units = min(units, max_units)

    def proceeds(quantity: Decimal) -> Decimal:
        remaining, revenue = quantity, Decimal(0)
        for level in levels:
            taken = min(remaining, Decimal(level.volume))
            revenue += taken * level.price
            remaining -= taken
            if remaining <= 0:
                break
        return revenue

    def profit(quantity: Decimal) -> Decimal:
        return proceeds(quantity) * (1 - query.sales_tax / 100) - (
            calculated.total_cost_per_unit * quantity
        )

    count = (
        product.buy_order_count
        if product.buy_levels is None
        else None
        if any(level.order_count is None for level in levels)
        else sum(level.order_count or 0 for level in levels)
    )
    return BuyDemandEstimate(
        revenue=proceeds(Decimal(units)),
        volume=volume,
        order_count=count,
        full_runs=units // calculated.units,
        units=units,
        profit=profit(Decimal(units)),
        daily_profit=profit(
            min(
                Decimal(units),
                calculated.units * 86400 * query.production_lines / calculated.seconds,
            )
        ),
        min_price=levels[-1].price if levels else None,
        average_price=proceeds(Decimal(units)) / units if units else None,
        depth_available=product.buy_levels is not None,
    )


def calculate_invention_daily_profit(
    profit: Decimal,
    runs: int,
    production_seconds: Decimal,
    runs_per_copy: int,
    probability: Decimal,
    attempt_seconds: Decimal,
    production_lines: int,
    invention_slots: int,
    cap_to_day: bool = True,
) -> Decimal:
    copies = (Decimal(runs) / runs_per_copy).to_integral_value(rounding=ROUND_CEILING)
    attempts = copies / probability
    invention_time = max(attempt_seconds, attempts * attempt_seconds / invention_slots)
    production_time = (Decimal(runs) / production_lines).to_integral_value(
        rounding=ROUND_CEILING
    ) * production_seconds
    rate = Decimal(86400) / (invention_time + production_time)
    return profit * (min(Decimal(1), rate) if cap_to_day else rate)
