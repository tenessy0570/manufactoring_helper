from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, DateTime, Numeric
from sqlalchemy.orm import Mapped, mapped_column

from app.core.orm import Base


class MarketPriceTable(Base):
    __tablename__ = "market_prices"

    hub_id: Mapped[str] = mapped_column(primary_key=True)
    type_id: Mapped[int] = mapped_column(primary_key=True)
    buy_price: Mapped[Decimal | None] = mapped_column(Numeric(24, 2))
    sell_price: Mapped[Decimal | None] = mapped_column(Numeric(24, 2))
    buy_volume: Mapped[int] = mapped_column(BigInteger)
    sell_volume: Mapped[int] = mapped_column(BigInteger)
    spread: Mapped[Decimal | None] = mapped_column(Numeric(24, 2))
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class MarketStateTable(Base):
    __tablename__ = "market_states"

    hub_id: Mapped[str] = mapped_column(primary_key=True)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    items: Mapped[int]
