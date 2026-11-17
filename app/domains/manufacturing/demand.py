from decimal import Decimal

from app.domains.manufacturing.models import (
    BuyDemandEstimate,
    ManufacturingQuery,
    ProfitCalculation,
)
from app.domains.market.models import BuyPriceLevel, MarketPrice


def estimate_buy_demand(
    product: MarketPrice, calculated: ProfitCalculation, query: ManufacturingQuery
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
        volume=volume,
        order_count=count,
        full_runs=units // calculated.units,
        units=units,
        profit=profit(Decimal(units)),
        daily_profit=profit(min(Decimal(units), calculated.units * 86400 / calculated.seconds)),
        min_price=levels[-1].price if levels else None,
        average_price=proceeds(Decimal(units)) / units if units else None,
        depth_available=product.buy_levels is not None,
    )
