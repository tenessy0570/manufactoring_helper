from abc import ABC, abstractmethod
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.profiles.models import Profile
from app.domains.profiles.tables import ProfileDefaultTable, ProfileTable


class ProfileRepository(ABC):
    @abstractmethod
    async def find(self) -> list[Profile]: ...

    @abstractmethod
    async def get(self, profile_id: UUID) -> Profile | None: ...

    @abstractmethod
    async def default_id(self, lock: bool = False) -> UUID: ...

    @abstractmethod
    async def save(self, profile: Profile) -> None: ...

    @abstractmethod
    async def set_default(self, profile_id: UUID) -> None: ...

    @abstractmethod
    async def delete(self, profile_id: UUID) -> None: ...


class SQLProfileRepository(ProfileRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def find(self) -> list[Profile]:
        rows = await self._session.scalars(
            select(ProfileTable).order_by(ProfileTable.created_at, ProfileTable.id)
        )
        return [Profile.model_validate(row, from_attributes=True) for row in rows]

    async def get(self, profile_id: UUID) -> Profile | None:
        row = await self._session.get(ProfileTable, profile_id)
        return None if row is None else Profile.model_validate(row, from_attributes=True)

    async def default_id(self, lock: bool = False) -> UUID:
        statement = select(ProfileDefaultTable.profile_id).where(ProfileDefaultTable.id == 1)
        if lock:
            statement = statement.with_for_update()
        result = await self._session.scalar(statement)
        if result is None:
            raise RuntimeError("Default profile is missing; run migrations")
        return result

    async def save(self, profile: Profile) -> None:
        await self._session.merge(
            ProfileTable(
                id=profile.id,
                name=profile.name,
                settings=profile.settings.model_dump(mode="json"),
                created_at=profile.created_at,
                updated_at=profile.updated_at,
            )
        )
        await self._session.flush()

    async def set_default(self, profile_id: UUID) -> None:
        await self._session.merge(ProfileDefaultTable(id=1, profile_id=profile_id))
        await self._session.flush()

    async def delete(self, profile_id: UUID) -> None:
        row = await self._session.get(ProfileTable, profile_id)
        if row is not None:
            await self._session.delete(row)
            await self._session.flush()
