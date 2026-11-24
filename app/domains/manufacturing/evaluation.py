from datetime import datetime
from decimal import Decimal

from app.core.config import DEFAULT_REFRESH, RefreshPolicy
from app.core.freshness import refresh_deadline
from app.domains.manufacturing.calculation import calculate
from app.domains.manufacturing.demand import estimate_buy_demand
from app.domains.manufacturing.filtering import matches_filters
from app.domains.manufacturing.models import (
    CalculationInput,
    ManufacturingQuery,
    Opportunity,
    OpportunityEvaluation,
    OpportunityInputs,
)
from app.domains.manufacturing.timing import calculate_timing


def evaluate_opportunities(
    inputs: OpportunityInputs,
    query: ManufacturingQuery,
    now: datetime,
    refresh_policy: RefreshPolicy = DEFAULT_REFRESH,
) -> OpportunityEvaluation:
    candidates, recipes = inputs.candidates, inputs.recipes
    quotes, products = inputs.quotes, inputs.products
    invention_settings, invention_results = inputs.invention_settings, inputs.invention_results
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
        preparation_seconds = Decimal(0)
        invention_plan = None
        invention_cost = Decimal(0)
        invention_status = "not_requested" if candidate.meta_group_id == 2 else "not_required"
        invention_option = None
        invention_complete = None
        invention_stale = False
        invention_deadline = None
        if (
            query.include_invention_cost
            or (query.include_invention_time or query.include_copying_time)
        ) and candidate.meta_group_id is None:
            missing_invention += 1
            invention_unavailable[candidate.type_id] = "unknown_meta_group"
            continue
        if (
            query.include_invention_cost
            or (query.include_invention_time or query.include_copying_time)
        ) and candidate.meta_group_id == 2:
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
            invention_plan = cached.result.best.plan
            if (query.include_invention_time and invention_plan.seconds_per_attempt is None) or (
                query.include_copying_time and invention_plan.copying_seconds_per_run is None
            ):
                missing_invention += 1
                invention_unavailable[candidate.type_id] = "time_pending"
                continue
            if query.include_invention_time:
                preparation_seconds += invention_plan.seconds_per_attempt or Decimal(0)
            if query.include_copying_time:
                preparation_seconds += invention_plan.copying_seconds_per_run or Decimal(0)
            if query.include_invention_cost:
                invention_cost = cached.result.best.expected_cost_per_unit
            invention_option = cached.result.best.plan.decryptor_name
            invention_complete = cached.result.complete_pricing
            invention_deadline = cached.expires_at
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
        deadlines = {
            "recipe": state.expires_at,
            "product_market": refresh_deadline(product.synced_at, refresh_policy.market),
            "material_market": min(
                refresh_deadline(quotes[m.type_id].synced_at, refresh_policy.market)
                for m in state.recipe.materials
            ),
            "history": refresh_deadline(candidate.synced_at, refresh_policy.history)
            if candidate.synced_at is not None
            else now,
        }
        if invention_deadline is not None:
            deadlines["invention"] = invention_deadline
        fresh_until = min(deadlines.values())
        stale_reasons = [source for source, deadline in deadlines.items() if deadline <= now]
        stale = bool(stale_reasons)
        if query.fresh_only and stale:
            continue
        is_buy = query.product_order_type == "buy"
        demand = estimate_buy_demand(product, calculated, query) if is_buy else None
        order_count = demand.order_count if demand else product.sell_order_count
        orders_at_price = product.buy_orders_at_best if is_buy else product.sell_orders_at_best
        runs_at_price = demand.full_runs if demand else None
        production_limit = demand.units if demand else None
        demand_profit = demand.profit if demand else None
        timing = calculate_timing(
            product, calculated, demand, query, invention_plan, preparation_seconds
        )
        limited_daily_profit, rank_daily_profit = (
            timing.demand_daily_profit,
            timing.daily_profit,
        )
        duration = timing.duration_seconds
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
        opportunity = Opportunity(
            demand_duration_seconds=duration,
            **calculated.model_dump(),
            type_id=candidate.type_id,
            name=candidate.name,
            blueprint_id=state.recipe.blueprint_id,
            meta_group_id=candidate.meta_group_id,
            invention_included=query.include_invention_cost and candidate.meta_group_id == 2,
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
            fresh_until=fresh_until,
            freshness_deadlines=deadlines,
        )
        if matches_filters(opportunity, query):
            results.append(opportunity)
    return OpportunityEvaluation(
        items=results,
        missing_recipes=missing_recipes,
        non_manufacturable=non_manufacturable,
        missing_prices=missing_prices,
        missing_job_costs=missing_job_costs,
        missing_invention=missing_invention,
        invention_unavailable=invention_unavailable,
    )
