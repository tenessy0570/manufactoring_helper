from datetime import datetime
from decimal import Decimal

from app.domains.market.models import MarketOrder, MarketPrice, TradeHub


class PriceAggregator:
    """Retains only best-price summaries, never the regional order book."""

    def __init__(self, hub: TradeHub, synced_at: datetime, expires_at: datetime) -> None:
        self._hub = hub
        self._synced_at = synced_at
        self._expires_at = expires_at
        self._prices: dict[int, MarketPrice] = {}

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
            price.buy_order_count = (price.buy_order_count or 0) + 1
            if price.buy_price is None or order.price > price.buy_price:
                price.buy_price, price.buy_volume = order.price, order.volume_remain
                price.buy_orders_at_best = 1
            elif order.price == price.buy_price:
                price.buy_volume += order.volume_remain
                price.buy_orders_at_best = (price.buy_orders_at_best or 0) + 1
        else:
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
            if price.buy_price is not None and price.sell_price is not None:
                price.spread = Decimal(price.sell_price - price.buy_price)
        return [self._prices[type_id] for type_id in sorted(self._prices)]
