from abc import ABC, abstractmethod
from collections.abc import Sequence
from datetime import UTC

from pydantic import TypeAdapter
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.invention.models import InventionRequest, InventionSettings, PlanState
from app.domains.invention.tables import InventionPlanTable, InventionRequestTable

_REQUESTS = TypeAdapter(list[InventionRequest])


class InventionRepository(ABC):
    @abstractmethod
    async def plan(self, key: str) -> PlanState | None: ...

    @abstractmethod
    async def save_plan(self, state: PlanState) -> None: ...

    @abstractmethod
    async def requests(self, keys: Sequence[str]) -> dict[str, InventionRequest]: ...

    @abstractmethod
    async def ensure_request(self, request: InventionRequest) -> None: ...

    @abstractmethod
    async def save_request(self, request: InventionRequest) -> None: ...

    @abstractmethod
    async def active_settings(self) -> list[InventionSettings]: ...


class SQLInventionRepository(InventionRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def plan(self, key: str) -> PlanState | None:
        row = await self._session.get(InventionPlanTable, key)
        if row is None:
            return None
        state = PlanState.model_validate(row, from_attributes=True)
        state.synced_at = (
            state.synced_at.replace(tzinfo=UTC)
            if state.synced_at.tzinfo is None
            else state.synced_at
        )
        state.expires_at = (
            state.expires_at.replace(tzinfo=UTC)
            if state.expires_at.tzinfo is None
            else state.expires_at
        )
        return state

    async def save_plan(self, state: PlanState) -> None:
        await self._session.merge(
            InventionPlanTable(
                key=state.key,
                plans=[plan.model_dump(mode="json") for plan in state.plans],
                synced_at=state.synced_at,
                expires_at=state.expires_at,
            )
        )
        await self._session.flush()

    async def requests(self, keys: Sequence[str]) -> dict[str, InventionRequest]:
        results: dict[str, InventionRequest] = {}
        for start in range(0, len(keys), 500):
            rows = await self._session.execute(
                select(InventionRequestTable.__table__).where(
                    InventionRequestTable.key.in_(keys[start : start + 500])
                )
            )
            for request in _REQUESTS.validate_python(rows.mappings().all()):
                request.updated_at = (
                    request.updated_at.replace(tzinfo=UTC)
                    if request.updated_at.tzinfo is None
                    else request.updated_at
                )
                request.expires_at = (
                    request.expires_at.replace(tzinfo=UTC)
                    if request.expires_at.tzinfo is None
                    else request.expires_at
                )
                results[request.key] = request
        return results

    async def ensure_request(self, request: InventionRequest) -> None:
        values = request.model_dump(mode="json")
        values.update(updated_at=request.updated_at, expires_at=request.expires_at)
        insert = (
            pg_insert if self._session.get_bind().dialect.name == "postgresql" else sqlite_insert
        )
        await self._session.execute(
            insert(InventionRequestTable)
            .values(**values)
            .on_conflict_do_nothing(index_elements=[InventionRequestTable.key])
        )

    async def save_request(self, request: InventionRequest) -> None:
        values = request.model_dump(mode="json")
        values.update(updated_at=request.updated_at, expires_at=request.expires_at)
        await self._session.merge(InventionRequestTable(**values))
        await self._session.flush()

    async def active_settings(self) -> list[InventionSettings]:
        rows = await self._session.scalars(select(InventionRequestTable.settings))
        return [InventionSettings.model_validate(row) for row in rows]
