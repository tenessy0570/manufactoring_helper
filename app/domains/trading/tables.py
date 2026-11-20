from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Numeric
from sqlalchemy.orm import Mapped, mapped_column

from app.core.orm import Base


class TradeMetadataTable(Base):
    __tablename__ = "trade_metadata"
    type_id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]
    volume_m3: Mapped[Decimal | None] = mapped_column(Numeric(24, 8))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
