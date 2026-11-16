from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime
from sqlalchemy.orm import Mapped, mapped_column

from app.core.orm import Base


class RecipeTable(Base):
    __tablename__ = "manufacturing_recipes"

    type_id: Mapped[int] = mapped_column(primary_key=True)
    recipe: Mapped[dict[str, Any] | None] = mapped_column(JSON(none_as_null=True))
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
