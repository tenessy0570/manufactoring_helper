from datetime import UTC, datetime
from decimal import ROUND_CEILING, Decimal

from app.core.freshness import MARKET_FRESHNESS, refresh_deadline
from app.domains.invention.models import (
    InventionSettings,
    ShoppingMaterial,
    ShoppingOption,
    ShoppingPlan,
)
from app.domains.invention.repository import InventionRepository
from app.domains.manufacturing.repository import ManufacturingRepository
from app.domains.market.models import HubId


def ceiling(value: Decimal) -> int:
    return int(value.to_integral_value(rounding=ROUND_CEILING))


class ShoppingService:
    def __init__(self, repository: InventionRepository, market: ManufacturingRepository) -> None:
        self._repository = repository
        self._market = market

    async def plan(self, type_id: int, units: int, hub: HubId = "jita") -> ShoppingPlan:
        source = await self._repository.plan(InventionSettings(type_id=type_id).plan_key)
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
            runs = ceiling(Decimal(units) / plan.units_per_run)
            copies = ceiling(Decimal(runs) / plan.runs_per_copy)
            attempts = ceiling(Decimal(copies) / probability)
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
                        ShoppingMaterial(type_id=m.type_id, quantity=ceiling(m.quantity * attempts))
                        for m in plan.materials
                    ],
                )
            )
        ids = sorted({m.type_id for option in result.options for m in option.materials})
        quotes = await self._market.quotes(hub, ids)
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
                    result.stale = result.stale or refresh_deadline(
                        quote.synced_at, MARKET_FRESHNESS
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
