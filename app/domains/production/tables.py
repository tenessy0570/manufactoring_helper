from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import JSON, DateTime, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column

from app.core.orm import Base


class ProductionTable(Base):
    __tablename__ = "productions"
    __table_args__ = (Index("ix_productions_user_created", "user_id", "created_at"),)
    id: Mapped[UUID] = mapped_column(primary_key=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    type_id: Mapped[int]
    name: Mapped[str]
    units: Mapped[int | None]
    actual_units: Mapped[int | None]
    actual_runs: Mapped[int | None]
    comment: Mapped[str]
    status: Mapped[str]
    entries: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
