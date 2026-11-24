from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.core.config import DEFAULT_REFRESH, RefreshPolicy
from app.core.repository import UnitOfWork
from app.domains.history.repository import HistoryRepository
from app.domains.invention.repository import InventionRepository
from app.domains.manufacturing.demand import estimate_buy_demand
from app.domains.manufacturing.evaluation import evaluate_opportunities
from app.domains.manufacturing.gateway import IndustryGateway
from app.domains.manufacturing.loading import OpportunityDataLoader
from app.domains.manufacturing.models import (
    BatchCalculation,
    CalculatorPage,
    CalculatorQuery,
    ManufacturingQuery,
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
        ttl_seconds: int = DEFAULT_REFRESH.recipe_seconds,
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
        now = self._clock()
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
        sync: ManufacturingSyncService | None = None,
        refresh_policy: RefreshPolicy = DEFAULT_REFRESH,
    ) -> None:
        self._repository, self._history, self._clock = repository, history, clock
        self._invention = invention
        self._sync = sync
        self._refresh = refresh_policy

    async def calculator(self, type_id: int, query: CalculatorQuery) -> CalculatorPage:
        if self._sync is not None:
            await self._sync.sync_if_stale(type_id)
        settings = {
            "hub_id",
            "material_hub_id",
            "material_order_type",
            "product_order_type",
            "sales_tax",
            "broker_fee",
            "buy_broker_fee",
            "sell_broker_fee",
            "facility_tax",
            "system_cost_index",
            "job_cost_per_run",
            "include_invention_cost",
            "buy_demand_tolerance_pct",
            "production_lines",
            "days",
        }
        calculation_query = ManufacturingQuery(
            **query.model_dump(include=settings), type_ids=[type_id], limit=1
        )
        page = await self.opportunities(calculation_query, restrict_to_mass_production=False)
        result = CalculatorPage(**page.model_dump())
        if not page.items:
            return result
        item = page.items[0]
        runs = query.manufacturing_runs
        units = item.units * runs
        covered_units = units
        gross: Decimal | None = item.revenue_per_unit * units
        if query.product_order_type == "buy":
            products = await self._repository.quotes(query.hub_id, [type_id])
            demand = estimate_buy_demand(products[type_id], item, calculation_query, units)
            covered_units = demand.units
            gross = demand.revenue if covered_units == units else None
        sales_tax = gross * query.sales_tax / 100 if gross is not None else None
        sales_broker = (
            gross * query.sell_broker_fee / 100
            if gross is not None and query.product_order_type == "sell"
            else Decimal(0)
            if gross is not None
            else None
        )
        net = (
            gross - sales_tax - sales_broker
            if gross is not None and sales_tax is not None and sales_broker is not None
            else None
        )
        total = item.total_cost_per_unit * units
        profit = net - total if net is not None else None
        material_cost = item.material_cost_per_unit * units
        result.batch = BatchCalculation(
            runs=runs,
            units=units,
            materials=[
                m.model_copy(update={"quantity": m.quantity * runs, "cost": m.cost * runs})
                for m in item.materials
            ],
            material_cost=material_cost,
            base_job_cost=item.base_job_cost_per_unit * units,
            facility_tax=item.facility_tax_per_unit * units,
            system_cost=item.system_cost_per_unit * units,
            job_cost=item.job_cost_per_unit * units,
            invention_cost=item.invention_cost_per_unit * units,
            procurement_broker_fee=item.procurement_broker_fee_per_unit * units,
            total_cost=total,
            gross_revenue=gross,
            sales_tax=sales_tax,
            sales_broker_fee=sales_broker,
            net_revenue=net,
            profit=profit,
            margin_pct=profit / material_cost * 100
            if profit is not None and material_cost
            else None,
            covered_units=covered_units,
        )
        return result

    async def opportunities(
        self, query: ManufacturingQuery, *, restrict_to_mass_production: bool = True
    ) -> OpportunityPage:
        now = self._clock()
        inputs = await OpportunityDataLoader(self._repository, self._history, self._invention).load(
            query, now, restrict_to_mass_production
        )
        evaluation = evaluate_opportunities(inputs, query, now, self._refresh)
        results = evaluation.items
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
            material_hub_id=query.material_hub_id or query.hub_id,
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
            missing_recipes=evaluation.missing_recipes,
            non_manufacturable=evaluation.non_manufacturable,
            missing_prices=evaluation.missing_prices,
            missing_job_costs=evaluation.missing_job_costs,
            missing_invention=evaluation.missing_invention,
            invention_unavailable=evaluation.invention_unavailable,
            limit=query.limit,
            offset=query.offset,
        )
