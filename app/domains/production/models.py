from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, computed_field

from app.domains.market.models import HubId

Money = Annotated[Decimal, Field(ge=0, le=10**18, decimal_places=2, allow_inf_nan=False)]
Kind = Literal["invention", "materials", "manufacturing", "income"]


class ProductionDetails(BaseModel):
    model_config = ConfigDict(extra="forbid")
    units: int | None = Field(default=None, ge=1, le=10**9)
    comment: str = Field(default="", max_length=2000)
    status: Literal["in_progress", "completed"] = "in_progress"


class ProductionCreate(ProductionDetails):
    type_id: int = Field(gt=0)


class EntryInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Kind
    amount: Money
    comment: str = Field(default="", max_length=2000)


class Entry(EntryInput):
    id: UUID
    created_at: datetime


class Production(ProductionCreate):
    id: UUID
    user_id: UUID
    name: str
    created_at: datetime
    updated_at: datetime
    entries: list[Entry] = Field(default_factory=list)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def totals(self) -> dict[str, Decimal | None]:
        totals: dict[str, Decimal | None] = {}
        for kind in ("invention", "materials", "manufacturing", "income"):
            values = [entry.amount for entry in self.entries if entry.kind == kind]
            totals[kind] = sum(values, Decimal(0)) if values else None
        costs = sum(
            (totals[kind] or Decimal(0) for kind in ("invention", "materials", "manufacturing")),
            Decimal(0),
        )
        totals["cost"] = costs
        balance = (totals["income"] or Decimal(0)) - costs
        totals["balance"] = balance
        totals["margin"] = balance / costs * 100 if costs else None
        return totals


class EstimateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["invention", "materials", "manufacturing"]
    units: int = Field(ge=1, le=10**9)
    hub_id: HubId = "jita"
    material_order_type: Literal["buy", "sell"] = "sell"
    buy_broker_fee: Decimal = Field(default=Decimal(0), ge=0, le=100, allow_inf_nan=False)
    facility_tax: Decimal = Field(default=Decimal(0), ge=0, le=100, allow_inf_nan=False)
    system_cost_index: Decimal = Field(default=Decimal(0), ge=0, le=100, allow_inf_nan=False)


class Estimate(BaseModel):
    amount: Decimal
    description: str
    stale: bool = False
    complete_comparison: bool = True
