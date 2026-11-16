import re
from abc import ABC, abstractmethod
from decimal import Decimal

from pydantic import BaseModel, Field, TypeAdapter

from app.domains.manufacturing.models import Material, Recipe
from app.infrastructure.http import HttpStatusError, ResilientHttpClient

DURATION = re.compile(
    r"P(?:(\d+)D)?(?:T(?:(\d+(?:\.\d+)?)H)?(?:(\d+(?:\.\d+)?)M)?(?:(\d+(?:\.\d+)?)S)?)?"
)


def duration_seconds(value: str) -> Decimal:
    match = DURATION.fullmatch(value)
    if match is None:
        raise ValueError("Invalid production duration")
    seconds = sum(
        (
            Decimal(part or 0) * multiplier
            for part, multiplier in zip(match.groups(), (86400, 3600, 60, 1), strict=True)
        ),
        Decimal(0),
    )
    if seconds <= 0:
        raise ValueError("Production duration must be positive")
    return seconds


class Production(BaseModel):
    product_id: int
    blueprint_id: int
    units: int = Field(gt=0)
    time: str
    me: int
    te: int
    runs: Decimal
    total_job_cost: Decimal = Field(ge=0)
    materials: dict[str, Material]


class IndustryGateway(ABC):
    @abstractmethod
    async def fetch(self, type_id: int) -> Recipe | None: ...


class IndustryClient(ResilientHttpClient):
    """Public EVE Ref industry transport, separate from reference-data endpoints."""


class EverefIndustryGateway(IndustryGateway):
    def __init__(self, client: IndustryClient) -> None:
        self._client = client

    async def fetch(self, type_id: int) -> Recipe | None:
        try:
            response = await self._client.request(
                "GET",
                "/v1/industry/cost",
                params={
                    "product_id": type_id,
                    "me": 0,
                    "te": 0,
                    "runs": 1,
                    "material_prices": "FUZZWORK_JITA_SELL_MIN",
                },
            )
        except HttpStatusError as error:
            if error.status_code == 404:
                return None
            if error.status_code == 400 and error.response is not None:
                try:
                    payload = error.response.json()
                    message = payload.get("message", "") if isinstance(payload, dict) else ""
                except ValueError:
                    message = ""
                expected = (
                    f"ClientException: Product type ID {type_id} is not produced from a blueprint"
                )
                if message == expected:
                    return None
            raise
        data = response.json(parse_float=Decimal)
        manufacturing = TypeAdapter(dict[str, Production]).validate_python(data["manufacturing"])
        production = manufacturing.get(str(type_id))
        if production is None:
            return None
        if (
            production.product_id != type_id
            or production.me != 0
            or production.te != 0
            or production.runs != 1
        ):
            raise ValueError("Unexpected production baseline")
        return Recipe(
            type_id=type_id,
            blueprint_id=production.blueprint_id,
            units=production.units,
            seconds=duration_seconds(production.time),
            job_cost=production.total_job_cost,
            materials=list(production.materials.values()),
        )
