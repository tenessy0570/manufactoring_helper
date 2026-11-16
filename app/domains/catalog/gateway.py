from abc import ABC, abstractmethod
from collections.abc import Sequence

from pydantic import BaseModel, TypeAdapter

from app.domains.catalog.models import MarketGroup
from app.infrastructure.esi import EsiClient
from app.infrastructure.everef import EverefClient
from app.infrastructure.http import HttpStatusError


class CatalogGateway(ABC):
    @abstractmethod
    async def list_market_group_ids(self) -> list[int]: ...

    @abstractmethod
    async def get_market_group(self, group_id: int) -> MarketGroup | None: ...

    @abstractmethod
    async def get_meta_group_id(self, type_id: int) -> int | None: ...

    @abstractmethod
    async def resolve_names(self, type_ids: Sequence[int]) -> dict[int, str]: ...


class ResolvedName(BaseModel):
    id: int
    name: str


class TypeMetadata(BaseModel):
    meta_group_id: int | None = None


class EsiEverefCatalogGateway(CatalogGateway):
    def __init__(self, esi: EsiClient, everef: EverefClient) -> None:
        self._esi = esi
        self._everef = everef

    async def list_market_group_ids(self) -> list[int]:
        return TypeAdapter(list[int]).validate_python(await self._esi.get_json("/markets/groups/"))

    async def get_market_group(self, group_id: int) -> MarketGroup | None:
        try:
            data = await self._esi.get_json(f"/markets/groups/{group_id}/")
        except HttpStatusError as error:
            if error.status_code == 404:
                return None
            raise
        return MarketGroup.model_validate(data)

    async def get_meta_group_id(self, type_id: int) -> int | None:
        try:
            data = await self._everef.get_json(f"/types/{type_id}")
        except HttpStatusError as error:
            if error.status_code == 404:
                return None
            raise
        return TypeMetadata.model_validate(data).meta_group_id

    async def resolve_names(self, type_ids: Sequence[int]) -> dict[int, str]:
        ids = sorted(set(type_ids))
        names: dict[int, str] = {}
        for start in range(0, len(ids), 1000):
            data = await self._esi.post_json("/universe/names/", ids[start : start + 1000])
            for item in TypeAdapter(list[ResolvedName]).validate_python(data):
                names[item.id] = item.name
        return names
