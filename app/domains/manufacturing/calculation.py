from decimal import Decimal

from app.domains.manufacturing.models import (
    CalculationInput,
    ManufacturingQuery,
    MaterialCost,
    ProfitCalculation,
)
from app.domains.market.enums import OrderSide


def calculate(data: CalculationInput, query: ManufacturingQuery) -> ProfitCalculation | None:
    recipe = data.recipe
    costs: list[MaterialCost] = []
    for material in recipe.materials:
        quote = data.quotes.get(material.type_id)
        if quote is None:
            return None
        price = (
            quote.buy_price
            if query.material_order_type == OrderSide.BUY.value
            else quote.sell_price
        )
        if price is None:
            return None
        quantity = material.quantity
        costs.append(
            MaterialCost(
                type_id=material.type_id,
                quantity=quantity,
                price=price,
                cost=quantity * price,
                volume_at_price=quote.buy_volume
                if query.material_order_type == OrderSide.BUY.value
                else quote.sell_volume,
            )
        )
    revenue = (
        data.product_quote.buy_price
        if query.product_order_type == OrderSide.BUY.value
        else data.product_quote.sell_price
    )
    if revenue is None:
        return None
    material_cost = sum((cost.cost for cost in costs), Decimal(0)) / recipe.units
    if material_cost <= 0:
        return None
    base_job_cost = (
        recipe.job_cost if query.job_cost_per_run is None else query.job_cost_per_run
    ) / recipe.units
    eiv = recipe.estimated_item_value
    if eiv is None and (query.facility_tax or query.system_cost_index):
        return None
    eiv_per_unit = None if eiv is None else eiv / recipe.units
    facility_tax = (eiv_per_unit or Decimal(0)) * query.facility_tax / 100
    system_cost = (eiv_per_unit or Decimal(0)) * query.system_cost_index / 100
    job_cost = base_job_cost + facility_tax + system_cost
    procurement_fee = (
        material_cost * query.buy_broker_fee / 100
        if query.material_order_type == OrderSide.BUY.value
        else Decimal(0)
    )
    sales_fee = (
        revenue * query.sell_broker_fee / 100
        if query.product_order_type == OrderSide.SELL.value
        else Decimal(0)
    )
    sales_tax = revenue * query.sales_tax / 100
    total_cost = material_cost + job_cost + procurement_fee + data.invention_cost_per_unit
    profit = revenue - sales_tax - sales_fee - total_cost
    seconds = recipe.seconds
    return ProfitCalculation(
        units=recipe.units,
        seconds=seconds,
        materials=costs,
        material_cost_per_unit=material_cost,
        job_cost_per_unit=job_cost,
        base_job_cost_per_unit=base_job_cost,
        facility_tax_per_unit=facility_tax,
        system_cost_per_unit=system_cost,
        estimated_item_value_per_unit=eiv_per_unit,
        invention_cost_per_unit=data.invention_cost_per_unit,
        procurement_broker_fee_per_unit=procurement_fee,
        sales_tax_per_unit=sales_tax,
        sales_broker_fee_per_unit=sales_fee,
        total_cost_per_unit=total_cost,
        revenue_per_unit=revenue,
        profit_per_unit=profit,
        margin_pct=profit / material_cost * 100,
        profit_per_day=profit * recipe.units * 86400 * query.production_lines / seconds,
    )
