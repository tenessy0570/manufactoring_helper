from uuid import UUID

from app.domains.manufacturing.models import ManufacturingQuery, OpportunityPage
from app.domains.manufacturing.service import ManufacturingService
from app.domains.profiles.service import ProfileService


class ProfileCalculationService:
    def __init__(self, profiles: ProfileService, manufacturing: ManufacturingService) -> None:
        self._profiles, self._manufacturing = profiles, manufacturing

    async def get_opportunities(
        self, profile_id: UUID | None, limit: int | None, offset: int
    ) -> OpportunityPage:
        profile = await self._profiles.get(profile_id)
        values = profile.settings.model_dump()
        values["offset"] = offset
        if limit is not None:
            values["limit"] = limit
        return await self._manufacturing.get_opportunities(
            ManufacturingQuery.model_validate(values)
        )
