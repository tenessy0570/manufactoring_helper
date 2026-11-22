from datetime import datetime
from decimal import Decimal

from app.domains.market.models import BuyPriceLevel, MarketOrder, MarketPrice, TradeHub


class PriceAggregator:
    """Retains station summaries and aggregated buy price levels, never raw regional orders."""

    def __init__(self, hub: TradeHub, synced_at: datetime, expires_at: datetime) -> None:
        self._hub = hub
        self._synced_at = synced_at
        self._expires_at = expires_at
        self._prices: dict[int, MarketPrice] = {}
        self._sell_levels: dict[int, dict[Decimal, BuyPriceLevel]] = {}
        self._buy_levels: dict[int, dict[Decimal, BuyPriceLevel]] = {}

    def add(self, order: MarketOrder) -> None:
        if order.location_id != self._hub.station_id or order.volume_remain == 0:
            return
        price = self._prices.setdefault(
            order.type_id,
            MarketPrice(
                hub_id=self._hub.hub_id,
                type_id=order.type_id,
                synced_at=self._synced_at,
                expires_at=self._expires_at,
                buy_order_count=0,
                sell_order_count=0,
                buy_orders_at_best=0,
                sell_orders_at_best=0,
            ),
        )
        if order.is_buy_order:
            levels = self._buy_levels.setdefault(order.type_id, {})
            level = levels.setdefault(
                order.price, BuyPriceLevel(price=order.price, volume=0, order_count=1)
            )
            if level.volume:
                level.order_count = (level.order_count or 0) + 1
            level.volume += order.volume_remain
            price.buy_order_count = (price.buy_order_count or 0) + 1
            if price.buy_price is None or order.price > price.buy_price:
                price.buy_price, price.buy_volume = order.price, order.volume_remain
                price.buy_orders_at_best = 1
            elif order.price == price.buy_price:
                price.buy_volume += order.volume_remain
                price.buy_orders_at_best = (price.buy_orders_at_best or 0) + 1
        else:
            levels = self._sell_levels.setdefault(order.type_id, {})
            level = levels.setdefault(order.price, BuyPriceLevel(price=order.price, volume=0))
            level.volume += order.volume_remain
            price.sell_order_count = (price.sell_order_count or 0) + 1
            if price.sell_price is None or order.price < price.sell_price:
                price.sell_price, price.sell_volume = order.price, order.volume_remain
                price.sell_orders_at_best = 1
            elif order.price == price.sell_price:
                price.sell_volume += order.volume_remain
                price.sell_orders_at_best = (price.sell_orders_at_best or 0) + 1

    def finish(self, expires_at: datetime) -> list[MarketPrice]:
        for price in self._prices.values():
            price.expires_at = expires_at
            sells = self._sell_levels.get(price.type_id, {})
            price.sell_levels = [sells[value] for value in sorted(sells)]
            levels = self._buy_levels.get(price.type_id, {})
            price.buy_levels = [levels[value] for value in sorted(levels, reverse=True)]
            if price.buy_price is not None and price.sell_price is not None:
                price.spread = Decimal(price.sell_price - price.buy_price)
        return [self._prices[type_id] for type_id in sorted(self._prices)]
