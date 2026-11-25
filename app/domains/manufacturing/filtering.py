from app.domains.manufacturing.models import ManufacturingQuery, Opportunity
from app.domains.market.enums import OrderSide


def matches_filters(item: Opportunity, query: ManufacturingQuery) -> bool:
    is_buy = query.product_order_type == OrderSide.BUY.value
    if any(
        minimum is not None and (value is None or value < minimum)
        for value, minimum in (
            (item.product_order_count, query.min_product_orders),
            (item.orders_at_price, query.min_orders_at_price),
            (
                (item.buy_demand_volume if is_buy else item.product_volume_at_price),
                query.min_product_volume,
            ),
        )
    ):
        return False
    if is_buy and (
        (query.require_full_run_demand and item.full_runs_at_buy_price == 0)
        or (query.exclude_fragile_buy_demand and item.demand_warnings)
    ):
        return False
    return not any(
        (low is not None and value < low) or (high is not None and value > high)
        for value, low, high in (
            (item.profit_per_unit, query.min_profit, query.max_profit),
            (item.margin_pct, query.min_margin, query.max_margin),
            (item.rank_profit_per_day, query.min_profit_per_day, None),
        )
    )
