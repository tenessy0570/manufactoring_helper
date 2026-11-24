from datetime import datetime
from decimal import Decimal

from app.core.config import DEFAULT_REFRESH, RefreshPolicy
from app.core.freshness import refresh_deadline
from app.domains.market.models import BuyPriceLevel
from app.domains.trading.models import TradeInput, TradeOpportunity, TradingQuery


def calculate_trade(
    data: TradeInput,
    query: TradingQuery,
    now: datetime,
    refresh_policy: RefreshPolicy = DEFAULT_REFRESH,
) -> TradeOpportunity | None:
    source, destination = data.source, data.destination
    if source.hub_id == destination.hub_id:
        return None
    purchase = source.sell_price if query.purchase_side == "sell" else source.buy_price
    sale = destination.buy_price if query.sale_side == "buy" else destination.sell_price
    if purchase is None or sale is None:
        return None
    volume = data.volume_m3
    if volume is None and query.max_cargo_m3 is not None:
        return None
    purchase_fee = (
        purchase * query.buy_broker_fee / 100 if query.purchase_side == "buy" else Decimal(0)
    )
    sale_rate = query.sales_tax + (
        query.sell_broker_fee if query.sale_side == "sell" else Decimal(0)
    )
    cost = purchase + purchase_fee
    profit = sale * (1 - sale_rate / 100) - cost
    if cost <= 0 or profit <= 0:
        return None
    margin = profit / cost * 100
    if (query.min_profit is not None and profit < query.min_profit) or (
        query.min_margin is not None and margin < query.min_margin
    ):
        return None
    stale = any(
        refresh_deadline(q.synced_at, refresh_policy.market) <= now for q in (source, destination)
    )
    if query.fresh_only and stale:
        return None
    warnings = []
    metadata_stale = data.metadata_expires_at is not None and data.metadata_expires_at <= now
    if volume is None:
        warnings.append("Transport volume is not loaded yet.")
    elif metadata_stale:
        warnings.append("Transport volume is due for refresh.")
        stale = True
        if query.fresh_only:
            return None
    if query.purchase_side == "sell" and source.sell_levels is None:
        warnings.append("Only best-price sell stock is available until the next market refresh.")
    purchase_levels = sorted(
        (
            level
            for level in (
                source.sell_levels or [BuyPriceLevel(price=purchase, volume=source.sell_volume)]
            )
            if level.price <= purchase * (1 + query.sell_price_range / 100)
        ),
        key=lambda level: level.price,
    )
    quantity = (
        sum(level.volume for level in purchase_levels)
        if query.purchase_side == "sell"
        else query.max_units
    )
    if query.purchase_side == "buy":
        warnings.append(
            "Purchase buy orders must fill first; quantity is a scenario, not available stock."
        )
    if query.sale_side == "sell":
        warnings.append("Listing at sell prices does not guarantee a sale or a selling time.")
    caps = [value for value in [quantity, query.max_units] if value is not None]
    if query.max_investment is not None:
        caps.append(int(query.max_investment // cost))
    if query.max_cargo_m3 is not None and volume:
        caps.append(int(query.max_cargo_m3 // volume))
    quantity = min(caps) if caps else None
    demand = None
    revenue = None
    levels: list[BuyPriceLevel] = []
    if query.sale_side == "buy":
        levels = destination.buy_levels or []
        if destination.buy_levels is None:
            levels = [BuyPriceLevel(price=sale, volume=destination.buy_volume)]
            warnings.append("Only best-price buy demand is available in this saved snapshot.")
        levels = sorted(
            (
                level
                for level in levels
                if level.price >= sale * (1 - query.buy_price_range / 100)
                and level.price * (1 - sale_rate / 100) > cost
            ),
            key=lambda level: level.price,
            reverse=True,
        )
        demand = sum(level.volume for level in levels)
        if quantity is not None:
            quantity = min(quantity, demand)
            remaining, revenue = quantity, Decimal(0)
            for level in levels:
                taken = min(remaining, level.volume)
                revenue += level.price * taken
                remaining -= taken
                if remaining <= 0:
                    break
    elif quantity is not None:
        revenue = sale * quantity
    depth_investment = None
    if query.purchase_side == "sell" and quantity is not None:
        destinations = (
            levels if query.sale_side == "buy" else [BuyPriceLevel(price=sale, volume=quantity)]
        )
        quantity, depth_investment, revenue = match_depth(
            purchase_levels, destinations, quantity, sale_rate, query.max_investment
        )
    if quantity is not None and quantity <= 0:
        return None
    investment = cost * quantity if quantity is not None else None
    if depth_investment is not None:
        investment = depth_investment
    net_revenue = revenue * (1 - sale_rate / 100) if revenue is not None else None
    batch_profit = (
        net_revenue - investment if net_revenue is not None and investment is not None else None
    )
    if query.min_batch_profit is not None and (
        batch_profit is None or batch_profit < query.min_batch_profit
    ):
        return None
    cargo = volume * quantity if volume is not None and quantity is not None else None
    density = (
        batch_profit / cargo
        if batch_profit is not None and cargo
        else profit / volume
        if volume
        else None
    )
    return TradeOpportunity(
        source_hub=source.hub_id,
        destination_hub=destination.hub_id,
        type_id=source.type_id,
        name=data.name or "Loading item name...",
        purchase_price=purchase,
        sale_price=sale,
        purchase_fee=purchase_fee,
        sale_fee=sale * sale_rate / 100,
        cost_per_unit=cost,
        profit_per_unit=profit,
        margin_pct=margin,
        volume_m3=volume,
        profit_per_m3=density,
        quantity=quantity,
        investment=investment,
        cargo_m3=cargo,
        batch_revenue=net_revenue,
        batch_profit=batch_profit,
        average_sale_price=revenue / quantity if revenue is not None and quantity else None,
        source_stock=sum(level.volume for level in purchase_levels)
        if query.purchase_side == "sell"
        else None,
        destination_demand=demand,
        source_updated_at=source.synced_at,
        destination_updated_at=destination.synced_at,
        stale=stale,
        instant_trade=query.purchase_side == "sell" and query.sale_side == "buy",
        warnings=warnings,
    )


def match_depth(
    purchases: list[BuyPriceLevel],
    sales: list[BuyPriceLevel],
    cap: int,
    sale_rate: Decimal,
    budget: Decimal | None,
) -> tuple[int, Decimal, Decimal]:
    quantity, spent, revenue = 0, Decimal(0), Decimal(0)
    index, available = 0, 0
    for purchase in purchases:
        remaining = purchase.volume
        while remaining > 0 and quantity < cap:
            if available == 0:
                if index >= len(sales):
                    return quantity, spent, revenue
                available = sales[index].volume
                index += 1
                if available == 0:
                    continue
            sale = sales[index - 1].price
            if sale * (1 - sale_rate / 100) <= purchase.price:
                return quantity, spent, revenue
            taken = min(remaining, available, cap - quantity)
            if budget is not None:
                taken = min(taken, int((budget - spent) // purchase.price))
            if taken <= 0:
                return quantity, spent, revenue
            quantity += taken
            spent += purchase.price * taken
            revenue += sale * taken
            remaining -= taken
            available -= taken
    return quantity, spent, revenue
