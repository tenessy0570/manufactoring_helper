from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.core.repository import UnitOfWork
from app.domains.catalog.models import MASS_PRODUCTION_META_GROUP_IDS
from app.domains.history.models import LiquidityItem, LiquidityQuery
from app.domains.history.repository import HistoryRepository
from app.domains.invention.models import InventionSettings
from app.domains.invention.repository import InventionRepository
from app.domains.manufacturing.calculation import calculate
from app.domains.manufacturing.demand import estimate_buy_demand
from app.domains.manufacturing.gateway import IndustryGateway
from app.domains.manufacturing.models import (
    CalculationInput,
    ManufacturingQuery,
    Opportunity,
    OpportunityPage,
    RecipeState,
)
from app.domains.manufacturing.repository import ManufacturingRepository


class ManufacturingSyncService:
    def __init__(
        self,
        repository: ManufacturingRepository,
        gateway: IndustryGateway,
        unit_of_work: UnitOfWork,
        ttl_seconds: int = 86400,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._repository, self._gateway, self._uow = repository, gateway, unit_of_work
        self._ttl, self._clock = ttl_seconds, clock

    async def sync_if_stale(self, type_id: int) -> bool:
        now = self._clock()
        previous = (await self._repository.recipes([type_id])).get(type_id)
        if (
            previous is not None
            and previous.expires_at > now
            and (previous.recipe is None or previous.recipe.estimated_item_value is not None)
        ):
            return False
        recipe = await self._gateway.fetch(type_id)
        state = RecipeState(
            type_id=type_id,
            recipe=recipe,
            synced_at=now,
            expires_at=now + timedelta(seconds=self._ttl),
        )
        try:
            await self._repository.save(state)
            await self._uow.commit()
        except BaseException:
            await self._uow.rollback()
            raise
        return True


class ManufacturingService:
    def __init__(
        self,
        repository: ManufacturingRepository,
        history: HistoryRepository,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        invention: InventionRepository | None = None,
    ) -> None:
        self._repository, self._history, self._clock = repository, history, clock
        self._invention = invention

    async def opportunities(self, query: ManufacturingQuery) -> OpportunityPage:
        now = self._clock()
        filters = LiquidityQuery.model_validate(
            query.model_dump(include=set(LiquidityQuery.model_fields))
        )
        filters.meta_group_ids = [
            value
            for value in MASS_PRODUCTION_META_GROUP_IDS
            if query.meta_group_ids is None or value in query.meta_group_ids
        ]
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
            if query.include_invention_cost and self._invention is not None
            else {}
        )
        results: list[Opportunity] = []
        missing_recipes = non_manufacturable = missing_prices = 0
        missing_job_costs = 0
        missing_invention = 0
        invention_unavailable: dict[int, str] = {}
        for candidate in candidates:
            state = recipes.get(candidate.type_id)
            if state is None:
                missing_recipes += 1
                continue
            if state.recipe is None:
                non_manufacturable += 1
                continue
            if state.recipe.estimated_item_value is None and (
                query.facility_tax or query.system_cost_index
            ):
                missing_job_costs += 1
                continue
            product = products.get(candidate.type_id)
            if product is None:
                missing_prices += 1
                continue
            invention_cost = Decimal(0)
            invention_status = "not_requested" if candidate.meta_group_id == 2 else "not_required"
            invention_option = None
            invention_complete = None
            invention_stale = False
            if query.include_invention_cost and candidate.meta_group_id is None:
                missing_invention += 1
                invention_unavailable[candidate.type_id] = "unknown_meta_group"
                continue
            if query.include_invention_cost and candidate.meta_group_id == 2:
                cached = invention_results.get(invention_settings[candidate.type_id].key)
                if (
                    cached is None
                    or cached.status != "ready"
                    or cached.result is None
                    or cached.result.best is None
                    or cached.result.best.expected_cost_per_unit is None
                ):
                    missing_invention += 1
                    invention_unavailable[candidate.type_id] = (
                        "not_requested" if cached is None else cached.status
                    )
                    continue
                invention_cost = cached.result.best.expected_cost_per_unit
                invention_option = cached.result.best.plan.decryptor_name
                invention_complete = cached.result.complete_pricing
                invention_stale = cached.expires_at <= now
                invention_status = "stale" if invention_stale else "ready"
            calculated = calculate(
                CalculationInput(
                    recipe=state.recipe,
                    quotes=quotes,
                    product_quote=product,
                    invention_cost_per_unit=invention_cost,
                ),
                query,
            )
            if calculated is None:
                missing_prices += 1
                continue
            stale = (
                state.expires_at <= now
                or invention_stale
                or product.expires_at <= now
                or any(
                    quotes[material.type_id].expires_at <= now
                    for material in state.recipe.materials
                )
            )
            if query.fresh_only and stale:
                continue
            is_buy = query.product_order_type == "buy"
            demand = estimate_buy_demand(product, calculated, query) if is_buy else None
            order_count = demand.order_count if demand else product.sell_order_count
            orders_at_price = product.buy_orders_at_best if is_buy else product.sell_orders_at_best
            volume = demand.volume if demand else product.sell_volume
            runs_at_price = demand.full_runs if demand else None
            production_limit = demand.units if demand else None
            demand_profit = demand.profit if demand else None
            limited_daily_profit = demand.daily_profit if demand else None
            rank_daily_profit = (
                calculated.profit_per_day if limited_daily_profit is None else limited_daily_profit
            )
            warnings: list[str] = []
            if is_buy:
                if order_count is None or orders_at_price is None:
                    warnings.append("buy_order_count_unknown")
                if order_count == 1:
                    warnings.append("single_buy_order")
                if orders_at_price == 1 and (
                    demand is None or not demand.depth_available or order_count in (None, 1)
                ):
                    warnings.append("single_buy_order_at_best")
                if runs_at_price == 0:
                    warnings.append("insufficient_buy_volume_for_one_run")
            if any(
                minimum is not None and (value is None or value < minimum)
                for value, minimum in (
                    (order_count, query.min_product_orders),
                    (orders_at_price, query.min_orders_at_price),
                    (volume, query.min_product_volume),
                )
            ):
                continue
            if is_buy and (
                (query.require_full_run_demand and runs_at_price == 0)
                or (query.exclude_fragile_buy_demand and warnings)
            ):
                continue
            if any(
                (low is not None and value < low) or (high is not None and value > high)
                for value, low, high in (
                    (calculated.profit_per_unit, query.min_profit, query.max_profit),
                    (calculated.margin_pct, query.min_margin, query.max_margin),
                    (rank_daily_profit, query.min_profit_per_day, None),
                )
            ):
                continue
            results.append(
                Opportunity(
                    **calculated.model_dump(),
                    type_id=candidate.type_id,
                    name=candidate.name,
                    blueprint_id=state.recipe.blueprint_id,
                    meta_group_id=candidate.meta_group_id,
                    invention_included=query.include_invention_cost
                    and candidate.meta_group_id == 2,
                    invention_status=invention_status,
                    invention_decryptor=invention_option,
                    invention_pricing_complete=invention_complete,
                    invention_required=None
                    if candidate.meta_group_id is None
                    else candidate.meta_group_id == 2,
                    recipe_synced_at=state.synced_at,
                    daily_isk_volume=candidate.daily_isk_volume,
                    daily_units=candidate.daily_units,
                    product_volume_at_price=product.buy_volume if is_buy else product.sell_volume,
                    buy_demand_volume=demand.volume if demand else None,
                    buy_demand_min_price=demand.min_price if demand else None,
                    buy_demand_average_price=demand.average_price if demand else None,
                    buy_demand_depth_available=demand.depth_available if demand else None,
                    product_order_count=order_count,
                    orders_at_price=orders_at_price,
                    full_runs_at_buy_price=runs_at_price,
                    production_limit_units=production_limit,
                    profit_at_current_buy_price=demand_profit,
                    demand_limited_profit_per_day=limited_daily_profit,
                    rank_profit_per_day=rank_daily_profit,
                    demand_warnings=warnings,
                    stale=stale,
                )
            )
        field = {
            "profit_per_day": "rank_profit_per_day",
            "margin": "margin_pct",
            "profit": "profit_per_unit",
            "demand_profit": "profit_at_current_buy_price",
        }[query.rank_by]
        results.sort(
            key=lambda result: (
                getattr(result, field) is None,
                -(getattr(result, field) or Decimal(0)),
                result.type_id,
            )
        )
        return OpportunityPage(
            hub_id=query.hub_id,
            material_hub_id=material_hub,
            material_order_type=query.material_order_type,
            product_order_type=query.product_order_type,
            sales_tax=query.sales_tax,
            broker_fee=query.broker_fee,
            buy_broker_fee=query.buy_broker_fee,
            sell_broker_fee=query.sell_broker_fee,
            facility_tax=query.facility_tax,
            system_cost_index=query.system_cost_index,
            items=results[query.offset : query.offset + query.limit],
            total=len(results),
            missing_recipes=missing_recipes,
            non_manufacturable=non_manufacturable,
            missing_prices=missing_prices,
            missing_job_costs=missing_job_costs,
            missing_invention=missing_invention,
            invention_unavailable=invention_unavailable,
            limit=query.limit,
            offset=query.offset,
        )
