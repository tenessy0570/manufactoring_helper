from datetime import datetime

from sqlalchemy import JSON, DateTime
from sqlalchemy.orm import Mapped, mapped_column

from app.core.orm import Base


class ItemTypeTable(Base):
    __tablename__ = "item_types"

    type_id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(index=True)
    market_group_id: Mapped[int] = mapped_column(index=True)
    market_group_name: Mapped[str]
    category: Mapped[str] = mapped_column(index=True)
    group_path: Mapped[list[int]] = mapped_column(JSON)
    is_rig: Mapped[bool] = mapped_column(index=True)
    meta_group_id: Mapped[int | None] = mapped_column(index=True)
    is_active: Mapped[bool] = mapped_column(index=True)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
