from datetime import datetime

from app.domains.catalog.models import MASS_PRODUCTION_META_GROUP_IDS
from app.domains.history.models import LiquidityQuery
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
        candidates = await self._history.find_candidates(filters, now)
        recipes = await self._repository.get_recipes(
            [candidate.type_id for candidate in candidates]
        )
        material_ids = sorted(
            {
                material.type_id
                for state in recipes.values()
                if state.recipe is not None
                for material in state.recipe.materials
            }
        )
        material_hub = query.material_hub_id or query.hub_id
        product_ids = [candidate.type_id for candidate in candidates]
        if material_hub == query.hub_id:
            all_quotes = await self._repository.get_quotes(
                material_hub, sorted(set(material_ids + product_ids))
            )
            quotes = {key: all_quotes[key] for key in material_ids if key in all_quotes}
            products = {key: all_quotes[key] for key in product_ids if key in all_quotes}
        else:
            quotes = await self._repository.get_quotes(material_hub, material_ids)
            products = await self._repository.get_quotes(query.hub_id, product_ids)
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
            await self._invention.get_requests([value.key for value in invention_settings.values()])
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
