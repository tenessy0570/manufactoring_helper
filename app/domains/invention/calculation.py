import hashlib
import json
from decimal import Decimal

from app.domains.invention.models import (
    InventionPlan,
    InventionResult,
    InventionSettings,
    PricedOption,
)
from app.domains.market.enums import OrderSide
from app.domains.market.models import MarketPrice


def price_plans(
    plans: list[InventionPlan], quotes: dict[int, MarketPrice], settings: InventionSettings
) -> InventionResult:
    options: list[PricedOption] = []
    for plan in plans:
        cost = Decimal(0)
        missing: list[int] = []
        for material in plan.materials:
            quote = quotes.get(material.type_id)
            price = (
                None
                if quote is None
                else quote.buy_price
                if settings.order_type == OrderSide.BUY.value
                else quote.sell_price
            )
            if price is None or price <= 0:
                missing.append(material.type_id)
            else:
                cost += material.quantity * price
        unit_cost = cost / (plan.probability * plan.runs_per_copy * plan.units_per_run)
        options.append(
            PricedOption(
                plan=plan,
                cost_per_attempt=None if missing else cost,
                expected_cost_per_unit=None if missing else unit_cost,
                missing_prices=missing,
            )
        )
    available = [option for option in options if option.expected_cost_per_unit is not None]
    best = (
        min(available, key=lambda option: option.expected_cost_per_unit or Decimal(0))
        if available
        else None
    )
    fingerprint = hashlib.sha256(
        json.dumps(
            {key: value.model_dump(mode="json") for key, value in sorted(quotes.items())},
            sort_keys=True,
        ).encode()
    ).hexdigest()
    return InventionResult(
        options=options,
        best=best,
        complete_pricing=all(not option.missing_prices for option in options),
        price_fingerprint=fingerprint,
    )
