from datetime import UTC, datetime
from decimal import ROUND_CEILING, Decimal

from app.core.config import DEFAULT_REFRESH, RefreshPolicy
from app.core.freshness import get_refresh_deadline
from app.domains.invention.models import (
    InventionSettings,
    ShoppingMaterial,
    ShoppingOption,
    ShoppingPlan,
)
from app.domains.invention.repository import InventionRepository
from app.domains.manufacturing.repository import ManufacturingRepository
from app.domains.market.models import HubId


def round_up_quantity(value: Decimal) -> int:
    return int(value.to_integral_value(rounding=ROUND_CEILING))


class ShoppingService:
    def __init__(
        self,
        repository: InventionRepository,
        market: ManufacturingRepository,
        refresh_policy: RefreshPolicy = DEFAULT_REFRESH,
    ) -> None:
        self._repository = repository
        self._market = market
        self._refresh_policy = refresh_policy

    async def get_shopping_plan(
        self, type_id: int, units: int, hub: HubId = "jita"
    ) -> ShoppingPlan:
        source = await self._repository.get_cached_plan(InventionSettings(type_id=type_id).plan_key)
        result = ShoppingPlan(
            type_id=type_id, desired_units=units, hub_id=hub, status="not_prepared"
        )
        if source is None:
            return result
        result.stale = source.expires_at <= datetime.now(UTC)
        result.status = "ready" if source.plans else "unsupported"
        for plan in source.plans:
            # Source assumes science V/V, encryption IV; target II/II/II has factor 71/86.
            probability = plan.probability * Decimal(71) / 86
            runs = round_up_quantity(Decimal(units) / plan.units_per_run)
            copies = round_up_quantity(Decimal(runs) / plan.runs_per_copy)
            attempts = round_up_quantity(Decimal(copies) / probability)
            result.options.append(
                ShoppingOption(
                    decryptor_id=plan.decryptor_id,
                    decryptor_name=plan.decryptor_name,
                    probability=probability,
                    runs_per_copy=plan.runs_per_copy,
                    units_per_run=plan.units_per_run,
                    source_blueprint_id=plan.source_blueprint_id,
                    invented_blueprint_id=plan.invented_blueprint_id,
                    manufacturing_runs=runs,
                    successful_copies=copies,
                    attempts=attempts,
                    output_capacity=copies * plan.runs_per_copy * plan.units_per_run,
                    materials=[
                        ShoppingMaterial(
                            type_id=material.type_id,
                            quantity=round_up_quantity(material.quantity * attempts),
                        )
                        for material in plan.materials
                    ],
                )
            )
        ids = sorted(
            {material.type_id for option in result.options for material in option.materials}
        )
        quotes = await self._market.get_quotes(hub, ids)
        for option in result.options:
            total = Decimal(0)
            for material in option.materials:
                quote = quotes.get(material.type_id)
                price = quote.sell_price if quote is not None else None
                if price is None or price <= 0:
                    option.missing_prices.append(material.type_id)
                else:
                    total += material.quantity * price
                    assert quote is not None
                    result.stale = result.stale or get_refresh_deadline(
                        quote.synced_at, self._refresh_policy.market
                    ) <= datetime.now(UTC)
            if not option.missing_prices:
                option.estimated_cost = total
        priced = [option for option in result.options if option.estimated_cost is not None]
        result.best = (
            min(priced, key=lambda option: (option.estimated_cost or Decimal(0), option.attempts))
            if priced
            else None
        )
        result.complete_pricing = all(not option.missing_prices for option in result.options)
        return result
