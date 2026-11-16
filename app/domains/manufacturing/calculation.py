from decimal import Decimal

from app.domains.manufacturing.models import (
    CalculationInput,
    ManufacturingQuery,
    MaterialCost,
    ProfitCalculation,
)


def calculate(data: CalculationInput, query: ManufacturingQuery) -> ProfitCalculation | None:
    recipe = data.recipe
    costs: list[MaterialCost] = []
    for material in recipe.materials:
        quote = data.quotes.get(material.type_id)
        if quote is None:
            return None
        price = quote.buy_price if query.material_order_type == "buy" else quote.sell_price
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
                if query.material_order_type == "buy"
                else quote.sell_volume,
            )
        )
    revenue = (
        data.product_quote.buy_price
        if query.product_order_type == "buy"
        else data.product_quote.sell_price
    )
    if revenue is None:
        return None
    material_cost = sum((cost.cost for cost in costs), Decimal(0)) / recipe.units
    if material_cost <= 0:
        return None
    job_cost = (
        recipe.job_cost if query.job_cost_per_run is None else query.job_cost_per_run
    ) / recipe.units
    procurement_fee = (
        material_cost * query.broker_fee / 100 if query.material_order_type == "buy" else Decimal(0)
    )
    sales_fee = (
        revenue * query.broker_fee / 100 if query.product_order_type == "sell" else Decimal(0)
    )
    sales_tax = revenue * query.sales_tax / 100
    total_cost = material_cost + job_cost + procurement_fee
    profit = revenue - sales_tax - sales_fee - total_cost
    seconds = recipe.seconds
    return ProfitCalculation(
        units=recipe.units,
        seconds=seconds,
        materials=costs,
        material_cost_per_unit=material_cost,
        job_cost_per_unit=job_cost,
        procurement_broker_fee_per_unit=procurement_fee,
        sales_tax_per_unit=sales_tax,
        sales_broker_fee_per_unit=sales_fee,
        total_cost_per_unit=total_cost,
        revenue_per_unit=revenue,
        profit_per_unit=profit,
        margin_pct=profit / material_cost * 100,
        profit_per_day=profit * recipe.units * 86400 / seconds,
    )
