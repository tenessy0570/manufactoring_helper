from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID, uuid4

from app.core.repository import UnitOfWork
from app.domains.manufacturing.models import ManufacturingQuery, OpportunityPage
from app.domains.manufacturing.service import ManufacturingService
from app.domains.profiles.models import Profile, ProfileCreate, ProfilePage, ProfileUpdate
from app.domains.profiles.repository import ProfileRepository


class ProfileNotFoundError(Exception):
    pass


class LastProfileError(Exception):
    pass


class ProfileService:
    def __init__(
        self,
        repository: ProfileRepository,
        unit_of_work: UnitOfWork,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._repository, self._uow, self._clock = repository, unit_of_work, clock

    async def find(self) -> ProfilePage:
        default = await self._repository.default_id()
        profiles = await self._repository.find()
        for profile in profiles:
            profile.is_default = profile.id == default
        return ProfilePage(items=profiles, default_profile_id=default)

    async def get(self, profile_id: UUID | None = None) -> Profile:
        default = await self._repository.default_id()
        profile = await self._repository.get(profile_id or default)
        if profile is None:
            raise ProfileNotFoundError
        profile.is_default = profile.id == default
        return profile

    async def create(self, data: ProfileCreate) -> Profile:
        await self._repository.default_id(lock=True)
        now = self._clock()
        profile = Profile(
            id=uuid4(), name=data.name, settings=data.settings, created_at=now, updated_at=now
        )
        try:
            await self._repository.save(profile)
            await self._uow.commit()
        except BaseException:
            await self._uow.rollback()
            raise
        return profile

    async def update(self, profile_id: UUID, data: ProfileUpdate) -> Profile:
        await self._repository.default_id(lock=True)
        profile = await self.get(profile_id)
        if data.name is not None:
            profile.name = data.name
        if data.settings is not None:
            profile.settings = data.settings
        profile.updated_at = self._clock()
        try:
            await self._repository.save(profile)
            await self._uow.commit()
        except BaseException:
            await self._uow.rollback()
            raise
        return profile

    async def copy(self, profile_id: UUID, name: str) -> Profile:
        source = await self.get(profile_id)
        return await self.create(
            ProfileCreate(name=name, settings=source.settings.model_copy(deep=True))
        )

    async def set_default(self, profile_id: UUID) -> Profile:
        await self._repository.default_id(lock=True)
        profile = await self.get(profile_id)
        try:
            await self._repository.set_default(profile_id)
            await self._uow.commit()
        except BaseException:
            await self._uow.rollback()
            raise
        profile.is_default = True
        return profile

    async def delete(self, profile_id: UUID) -> None:
        default = await self._repository.default_id(lock=True)
        await self.get(profile_id)
        remaining = [
            profile for profile in await self._repository.find() if profile.id != profile_id
        ]
        if not remaining:
            raise LastProfileError
        try:
            if default == profile_id:
                await self._repository.set_default(remaining[0].id)
            await self._repository.delete(profile_id)
            await self._uow.commit()
        except BaseException:
            await self._uow.rollback()
            raise


class ProfileCalculationService:
    def __init__(self, profiles: ProfileService, manufacturing: ManufacturingService) -> None:
        self._profiles, self._manufacturing = profiles, manufacturing

    async def opportunities(
        self, profile_id: UUID | None, limit: int | None, offset: int
    ) -> OpportunityPage:
        profile = await self._profiles.get(profile_id)
        values = profile.settings.model_dump()
        values["offset"] = offset
        if limit is not None:
            values["limit"] = limit
        return await self._manufacturing.opportunities(ManufacturingQuery.model_validate(values))
