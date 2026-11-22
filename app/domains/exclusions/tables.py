from typing import Any
from uuid import UUID

from sqlalchemy import JSON, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.core.orm import Base


class ExclusionsTable(Base):
    __tablename__ = "user_opportunity_exclusions"
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    items: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
