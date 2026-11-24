from datetime import datetime

from app.domains.catalog.models import MASS_PRODUCTION_META_GROUP_IDS
from app.domains.history.models import LiquidityItem, LiquidityQuery
from app.domains.history.repository import HistoryRepository
from app.domains.invention.models import InventionSettings
from app.domains.invention.repository import InventionRepository
from app.domains.manufacturing.models import ManufacturingQuery, OpportunityInputs
from app.domains.manufacturing.repository import ManufacturingRepository


class OpportunityDataLoader:
    def __init__(
        self,
        repository: ManufacturingRepository,
        history: HistoryRepository,
        invention: InventionRepository | None,
    ) -> None:
        self._repository, self._history, self._invention = repository, history, invention

    async def load(
        self, query: ManufacturingQuery, now: datetime, restrict_to_mass_production: bool
    ) -> OpportunityInputs:
        filters = LiquidityQuery.model_validate(
            query.model_dump(include=set(LiquidityQuery.model_fields))
        )
        if restrict_to_mass_production:
            filters.meta_group_ids = [
                value
                for value in MASS_PRODUCTION_META_GROUP_IDS
                if query.meta_group_ids is None or value in query.meta_group_ids
            ]
        filters.fresh_only = False
        filters.limit, filters.offset = 500, 0
        candidates: list[LiquidityItem] = []
        while True:
            batch, total = await self._history.liquidity(filters, now)
            candidates.extend(batch)
            filters.offset += filters.limit
            if filters.offset >= total:
                break
        recipes = await self._repository.recipes([candidate.type_id for candidate in candidates])
        material_ids = sorted(
            {
                material.type_id
                for state in recipes.values()
                if state.recipe is not None
                for material in state.recipe.materials
            }
        )
        material_hub = query.material_hub_id or query.hub_id
        quotes = await self._repository.quotes(material_hub, material_ids)
        products = await self._repository.quotes(
            query.hub_id, [candidate.type_id for candidate in candidates]
        )
        invention_settings = {
            candidate.type_id: InventionSettings(
                type_id=candidate.type_id,
                hub_id=material_hub,
                order_type=query.material_order_type,
            )
            for candidate in candidates
            if candidate.meta_group_id == 2
        }
        invention_results = (
            await self._invention.requests([value.key for value in invention_settings.values()])
            if (
                query.include_invention_cost
                or (query.include_invention_time or query.include_copying_time)
            )
            and self._invention is not None
            else {}
        )
        return OpportunityInputs(
            candidates=candidates,
            recipes=recipes,
            quotes=quotes,
            products=products,
            invention_settings=invention_settings,
            invention_results=invention_results,
        )
