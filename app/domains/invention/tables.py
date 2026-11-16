from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime
from sqlalchemy.orm import Mapped, mapped_column

from app.core.orm import Base


class InventionPlanTable(Base):
    __tablename__ = "invention_plans"
    key: Mapped[str] = mapped_column(primary_key=True)
    plans: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class InventionRequestTable(Base):
    __tablename__ = "invention_requests"
    key: Mapped[str] = mapped_column(primary_key=True)
    settings: Mapped[dict[str, Any]] = mapped_column(JSON)
    status: Mapped[str]
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON(none_as_null=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    error_type: Mapped[str | None]
