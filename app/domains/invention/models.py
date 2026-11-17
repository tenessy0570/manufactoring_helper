import hashlib
import json
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.domains.market.models import HubId

DECRYPTORS: tuple[tuple[int | None, str], ...] = (
    (None, "None"),
    (34201, "Accelerant"),
    (34202, "Attainment"),
    (34203, "Augmentation"),
    (34207, "Optimized Attainment"),
    (34208, "Optimized Augmentation"),
    (34204, "Parity"),
    (34205, "Process"),
    (34206, "Symmetry"),
)
QUEUE = "arq:invention"
SCIENCE_LEVEL = 5
ENCRYPTION_LEVEL = 4


class InventionQuery(BaseModel):
    model_config = ConfigDict(frozen=True)

    hub_id: HubId = "jita"
    order_type: Literal["buy", "sell"] = "sell"


class InventionSettings(InventionQuery):
    type_id: int = Field(gt=0)

    @property
    def plan_key(self) -> str:
        return f"v1:{self.type_id}:{SCIENCE_LEVEL}:{ENCRYPTION_LEVEL}"

    @property
    def key(self) -> str:
        data = self.model_dump(mode="json")
        # Keep the former zero-fee key; legacy fees never split plans or valuations.
        data.update(science_level=SCIENCE_LEVEL, encryption_level=ENCRYPTION_LEVEL, broker_fee="0")
        return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


class InventionMaterial(BaseModel):
    type_id: int
    quantity: Decimal = Field(gt=0, allow_inf_nan=False)


class InventionPlan(BaseModel):
    decryptor_id: int | None
    decryptor_name: str
    source_blueprint_id: int
    invented_blueprint_id: int
    probability: Decimal = Field(gt=0, le=1, allow_inf_nan=False)
    runs_per_copy: int = Field(gt=0)
    units_per_run: int = Field(gt=0)
    materials: list[InventionMaterial] = Field(min_length=1)
    job_cost_per_attempt: Decimal = Field(ge=0, allow_inf_nan=False)
    me: int
    te: int


class PlanState(BaseModel):
    key: str
    plans: list[InventionPlan]
    synced_at: datetime
    expires_at: datetime


class PricedOption(BaseModel):
    plan: InventionPlan
    cost_per_attempt: Decimal | None
    expected_cost_per_unit: Decimal | None
    missing_prices: list[int]


class InventionResult(BaseModel):
    options: list[PricedOption]
    best: PricedOption | None
    complete_pricing: bool
    price_fingerprint: str


class InventionRequest(BaseModel):
    key: str
    settings: InventionSettings
    status: Literal["pending", "ready", "missing_prices", "unsupported", "error"] = "pending"
    result: InventionResult | None = None
    updated_at: datetime
    expires_at: datetime
    error_type: str | None = None


class InventionView(BaseModel):
    request: InventionRequest | None
    stale: bool
    queued: bool = False
