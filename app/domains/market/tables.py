from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import JSON, BigInteger, DateTime, Numeric
from sqlalchemy.orm import Mapped, mapped_column

from app.core.orm import Base


class MarketPriceTable(Base):
    __tablename__ = "market_prices"

    hub_id: Mapped[str] = mapped_column(primary_key=True)
    type_id: Mapped[int] = mapped_column(primary_key=True)
    sell_levels: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON(none_as_null=True))
    buy_levels: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON(none_as_null=True))
    buy_price: Mapped[Decimal | None] = mapped_column(Numeric(24, 2))
    sell_price: Mapped[Decimal | None] = mapped_column(Numeric(24, 2))
    buy_volume: Mapped[int] = mapped_column(BigInteger)
    sell_volume: Mapped[int] = mapped_column(BigInteger)
    buy_order_count: Mapped[int | None]
    sell_order_count: Mapped[int | None]
    buy_orders_at_best: Mapped[int | None]
    sell_orders_at_best: Mapped[int | None]
    spread: Mapped[Decimal | None] = mapped_column(Numeric(24, 2))
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class MarketStateTable(Base):
    __tablename__ = "market_states"

    hub_id: Mapped[str] = mapped_column(primary_key=True)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    items: Mapped[int]
