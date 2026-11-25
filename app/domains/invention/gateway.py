from abc import ABC, abstractmethod
from decimal import Decimal

from pydantic import BaseModel, Field, TypeAdapter

from app.core.concurrency import gather_all
from app.domains.invention.models import (
    DECRYPTORS,
    ENCRYPTION_LEVEL,
    SCIENCE_LEVEL,
    InventionMaterial,
    InventionPlan,
    InventionSettings,
)
from app.domains.manufacturing.gateway import IndustryClient, parse_duration_seconds
from app.infrastructure.http import HttpStatusError

# Public IndustryCostInput skill parameters; all relevant science skills share the supplied level.
SCIENCE_SKILLS = (
    "amarr_starship_engineering",
    "caldari_starship_engineering",
    "core_subsystem_technology",
    "defensive_subsystem_technology",
    "electromagnetic_physics",
    "electronic_engineering",
    "gallente_starship_engineering",
    "graviton_physics",
    "high_energy_physics",
    "hydromagnetic_physics",
    "laser_physics",
    "mechanical_engineering",
    "metallurgy",
    "minmatar_starship_engineering",
    "molecular_engineering",
    "mutagenic_stabilization",
    "nanite_engineering",
    "nuclear_physics",
    "offensive_subsystem_technology",
    "plasma_physics",
    "propulsion_subsystem_technology",
    "quantum_physics",
    "rocket_science",
    "science",
    "triglavian_quantum_engineering",
    "upwell_starship_engineering",
)
ENCRYPTION_SKILLS = tuple(
    f"{race}_encryption_methods"
    for race in (
        "amarr",
        "caldari",
        "gallente",
        "minmatar",
        "sleeper",
        "triglavian",
        "upwell",
    )
)


class CopyingResponse(BaseModel):
    product_id: int
    runs: Decimal = Field(gt=0)
    time: str


class InventionResponse(BaseModel):
    time: str | None = None
    product_id: int
    blueprint_id: int
    probability: Decimal = Field(gt=0, le=1)
    runs: Decimal = Field(gt=0)
    runs_per_copy: int = Field(gt=0)
    units_per_run: int = Field(gt=0)
    materials: dict[str, InventionMaterial]
    total_job_cost: Decimal = Field(ge=0)
    me: int
    te: int


class InventionGateway(ABC):
    @abstractmethod
    async def fetch(self, settings: InventionSettings) -> list[InventionPlan]: ...


class EverefInventionGateway(InventionGateway):
    def __init__(self, client: IndustryClient) -> None:
        self._client = client

    async def fetch(self, settings: InventionSettings) -> list[InventionPlan]:
        async def parse_option(decryptor_id: int | None, name: str) -> InventionPlan | None:
            params: dict[str, int] = {skill: SCIENCE_LEVEL for skill in SCIENCE_SKILLS}
            params.update({skill: ENCRYPTION_LEVEL for skill in ENCRYPTION_SKILLS})
            params.update({"product_id": settings.type_id, "runs": 1, "me": 0, "te": 0})
            if decryptor_id is not None:
                params["decryptor_id"] = decryptor_id
            try:
                response = await self._client.request("GET", "/v1/industry/cost", params=params)
            except HttpStatusError as error:
                if error.status_code == 400 and error.response is not None:
                    expected = (
                        f"ClientException: Product type ID {settings.type_id} "
                        "is not produced from a blueprint"
                    )
                    try:
                        error_payload = error.response.json()
                    except ValueError:
                        error_payload = None
                    if error_payload == {"message": expected}:
                        return None
                raise
            data = response.json(parse_float=Decimal)
            if not isinstance(data.get("manufacturing"), dict):
                raise ValueError("Missing manufacturing data in invention response")
            entries = TypeAdapter(dict[str, InventionResponse]).validate_python(
                data.get("invention", {})
            )
            production = data.get("manufacturing", {}).get(str(settings.type_id))
            if not entries:
                return None
            if production is None:
                raise ValueError("Cannot link invention to the requested manufacturing product")
            invented_id = int(production["blueprint_id"])
            entry = entries.get(str(invented_id))
            if entry is None or entry.product_id != invented_id:
                raise ValueError("Unexpected invention blueprint")
            copy_data = data.get("copying", {}).get(str(entry.blueprint_id))
            copying = CopyingResponse.model_validate(copy_data) if copy_data else None
            if copying is not None and copying.product_id != entry.blueprint_id:
                raise ValueError("Unexpected copying blueprint")
            return InventionPlan(
                copying_seconds_per_run=parse_duration_seconds(copying.time) / copying.runs
                if copying is not None
                else None,
                seconds_per_attempt=parse_duration_seconds(entry.time) / entry.runs
                if entry.time
                else None,
                decryptor_id=decryptor_id,
                decryptor_name=name,
                source_blueprint_id=entry.blueprint_id,
                invented_blueprint_id=invented_id,
                probability=entry.probability,
                runs_per_copy=entry.runs_per_copy,
                units_per_run=entry.units_per_run,
                me=entry.me,
                te=entry.te,
                job_cost_per_attempt=entry.total_job_cost / entry.runs,
                materials=[
                    InventionMaterial(
                        type_id=material.type_id, quantity=material.quantity / entry.runs
                    )
                    for material in entry.materials.values()
                ],
            )

        baseline = await parse_option(None, "None")
        if baseline is None:
            return []
        plans = await gather_all(
            parse_option(decryptor_id, name) for decryptor_id, name in DECRYPTORS[1:]
        )
        if any(plan is None for plan in plans):
            raise ValueError("Incomplete invention options; previous plan preserved")
        return [baseline, *[plan for plan in plans if plan is not None]]
