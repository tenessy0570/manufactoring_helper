from datetime import date as calendar_date
from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, DateTime, Numeric
from sqlalchemy.orm import Mapped, mapped_column

from app.core.orm import Base


class HistoryDayTable(Base):
    __tablename__ = "market_history"

    region_id: Mapped[int] = mapped_column(primary_key=True)
    type_id: Mapped[int] = mapped_column(primary_key=True)
    date: Mapped[calendar_date] = mapped_column(primary_key=True)
    average: Mapped[Decimal] = mapped_column(Numeric(38, 12))
    highest: Mapped[Decimal] = mapped_column(Numeric(38, 12))
    lowest: Mapped[Decimal] = mapped_column(Numeric(38, 12))
    volume: Mapped[int] = mapped_column(BigInteger)
    order_count: Mapped[int] = mapped_column(BigInteger)


class HistoryStateTable(Base):
    __tablename__ = "market_history_states"

    region_id: Mapped[int] = mapped_column(primary_key=True)
    type_id: Mapped[int] = mapped_column(primary_key=True)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
