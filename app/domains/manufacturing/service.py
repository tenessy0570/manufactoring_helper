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
from app.domains.market.enums import OrderSide


class ManufacturingSyncService:
    def __init__(
        self,
        repository: ManufacturingRepository,
        gateway: IndustryGateway,
        unit_of_work: UnitOfWork,
        ttl_seconds: int = DEFAULT_REFRESH.recipe_seconds,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._repository, self._gateway, self._unit_of_work = repository, gateway, unit_of_work
        self._cache_ttl_seconds, self._clock = ttl_seconds, clock

    async def sync_if_stale(self, type_id: int) -> bool:
        now = self._clock()
        previous = (await self._repository.get_recipes([type_id])).get(type_id)
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
            expires_at=now + timedelta(seconds=self._cache_ttl_seconds),
        )
        try:
            await self._repository.save(state)
            await self._unit_of_work.commit()
        except BaseException:
            await self._unit_of_work.rollback()
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
        self._refresh_policy = refresh_policy

    async def get_calculator_page(
        self, type_id: int, calculator_query: CalculatorQuery
    ) -> CalculatorPage:
        if self._sync is not None:
            await self._sync.sync_if_stale(type_id)
        query_field_names = {
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
            **calculator_query.model_dump(include=query_field_names), type_ids=[type_id], limit=1
        )
        opportunities_page = await self.get_opportunities(
            calculation_query, restrict_to_mass_production=False
        )
        calculator_page = CalculatorPage(**opportunities_page.model_dump())
        if not opportunities_page.items:
            return calculator_page
        opportunity = opportunities_page.items[0]
        manufacturing_runs = calculator_query.manufacturing_runs
        finished_units = opportunity.units * manufacturing_runs
        covered_units = finished_units
        gross_revenue: Decimal | None = opportunity.revenue_per_unit * finished_units
        if calculator_query.product_order_type == OrderSide.BUY.value:
            products = await self._repository.get_quotes(calculator_query.hub_id, [type_id])
            demand = estimate_buy_demand(
                products[type_id], opportunity, calculation_query, finished_units
            )
            covered_units = demand.units
            gross_revenue = demand.revenue if covered_units == finished_units else None
        sales_tax = (
            gross_revenue * calculator_query.sales_tax / 100 if gross_revenue is not None else None
        )
        sales_broker_fee = (
            gross_revenue * calculator_query.sell_broker_fee / 100
            if gross_revenue is not None
            and calculator_query.product_order_type == OrderSide.SELL.value
            else Decimal(0)
            if gross_revenue is not None
            else None
        )
        net_revenue = (
            gross_revenue - sales_tax - sales_broker_fee
            if gross_revenue is not None and sales_tax is not None and sales_broker_fee is not None
            else None
        )
        total_cost = opportunity.total_cost_per_unit * finished_units
        net_profit = net_revenue - total_cost if net_revenue is not None else None
        material_cost = opportunity.material_cost_per_unit * finished_units
        calculator_page.batch = BatchCalculation(
            runs=manufacturing_runs,
            units=finished_units,
            materials=[
                material.model_copy(
                    update={
                        "quantity": material.quantity * manufacturing_runs,
                        "cost": material.cost * manufacturing_runs,
                    }
                )
                for material in opportunity.materials
            ],
            material_cost=material_cost,
            base_job_cost=opportunity.base_job_cost_per_unit * finished_units,
            facility_tax=opportunity.facility_tax_per_unit * finished_units,
            system_cost=opportunity.system_cost_per_unit * finished_units,
            job_cost=opportunity.job_cost_per_unit * finished_units,
            invention_cost=opportunity.invention_cost_per_unit * finished_units,
            procurement_broker_fee=opportunity.procurement_broker_fee_per_unit * finished_units,
            total_cost=total_cost,
            gross_revenue=gross_revenue,
            sales_tax=sales_tax,
            sales_broker_fee=sales_broker_fee,
            net_revenue=net_revenue,
            profit=net_profit,
            margin_pct=net_profit / material_cost * 100
            if net_profit is not None and material_cost
            else None,
            covered_units=covered_units,
        )
        return calculator_page

    async def get_opportunities(
        self, opportunity_query: ManufacturingQuery, *, restrict_to_mass_production: bool = True
    ) -> OpportunityPage:
        now = self._clock()
        opportunity_inputs = await OpportunityDataLoader(
            self._repository, self._history, self._invention
        ).load(opportunity_query, now, restrict_to_mass_production)
        evaluation_result = evaluate_opportunities(
            opportunity_inputs, opportunity_query, now, self._refresh_policy
        )
        opportunities = evaluation_result.items
        ranking_field = {
            "profit_per_day": "rank_profit_per_day",
            "margin": "margin_pct",
            "profit": "profit_per_unit",
            "demand_profit": "profit_at_current_buy_price",
        }[opportunity_query.rank_by]
        opportunities.sort(
            key=lambda opportunity: (
                getattr(opportunity, ranking_field) is None,
                -(getattr(opportunity, ranking_field) or Decimal(0)),
                opportunity.type_id,
            )
        )
        return OpportunityPage(
            hub_id=opportunity_query.hub_id,
            material_hub_id=opportunity_query.material_hub_id or opportunity_query.hub_id,
            material_order_type=opportunity_query.material_order_type,
            product_order_type=opportunity_query.product_order_type,
            sales_tax=opportunity_query.sales_tax,
            broker_fee=opportunity_query.broker_fee,
            buy_broker_fee=opportunity_query.buy_broker_fee,
            sell_broker_fee=opportunity_query.sell_broker_fee,
            facility_tax=opportunity_query.facility_tax,
            system_cost_index=opportunity_query.system_cost_index,
            items=opportunities[
                opportunity_query.offset : opportunity_query.offset + opportunity_query.limit
            ],
            total=len(opportunities),
            missing_recipes=evaluation_result.missing_recipes,
            non_manufacturable=evaluation_result.non_manufacturable,
            missing_prices=evaluation_result.missing_prices,
            missing_job_costs=evaluation_result.missing_job_costs,
            missing_invention=evaluation_result.missing_invention,
            invention_unavailable=evaluation_result.invention_unavailable,
            limit=opportunity_query.limit,
            offset=opportunity_query.offset,
        )
