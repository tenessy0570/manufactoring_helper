import asyncio
import multiprocessing
import re
from collections import defaultdict
from datetime import UTC, datetime
from decimal import Decimal
from multiprocessing.connection import Connection
from types import SimpleNamespace
from typing import Any

from app.domains.market.models import HUBS, BuyPriceLevel, get_hub
from app.domains.trading.calculation import calculate_trade
from app.domains.trading.models import (
    CargoLine,
    CargoPlan,
    CargoQuery,
    CargoResult,
    TradeInput,
    TradingQuery,
)
from app.domains.trading.repository import TradingRepository
from app.domains.trading.routes import TradingRoutes

SOLVERS = asyncio.Semaphore(1)


def segments(data: TradeInput, query: CargoQuery) -> list[tuple[int, Decimal, Decimal]]:
    source, target = data.source, data.destination
    sale_price = target.buy_price if query.sale_side == "buy" else target.sell_price
    if source.sell_price is None or sale_price is None:
        return []
    buys = sorted(
        (
            v
            for v in (
                source.sell_levels
                or [BuyPriceLevel(price=source.sell_price, volume=source.sell_volume)]
            )
            if v.volume > 0 and v.price <= source.sell_price * (1 + query.sell_price_range / 100)
        ),
        key=lambda v: v.price,
    )
    sells = sorted(
        (
            v
            for v in (
                target.buy_levels or [BuyPriceLevel(price=sale_price, volume=target.buy_volume)]
            )
            if v.volume > 0 and v.price >= sale_price * (1 - query.buy_price_range / 100)
        ),
        key=lambda v: v.price,
        reverse=True,
    )
    if query.sale_side == "sell":
        sells = [BuyPriceLevel(price=sale_price, volume=sum(v.volume for v in buys))]
    result = []
    i, j = 0, 0
    left, right = 0, 0
    while i < len(buys) and j < len(sells):
        left = left or buys[i].volume
        right = right or sells[j].volume
        net = sells[j].price * (1 - query.sales_tax / 100)
        if net <= buys[i].price:
            break
        count = min(left, right)
        result.append((count, buys[i].price, net))
        left -= count
        right -= count
        i += left == 0
        j += right == 0
    return result


def optimize(
    inputs: list[TradeInput], query: CargoQuery, run_solver: bool = True
) -> tuple[list[CargoLine], bool]:
    from scipy.optimize import Bounds, LinearConstraint, milp  # type: ignore[import-untyped]

    choices = [
        (data, count, cost, net)
        for data in inputs
        for count, cost, net in segments(data, query)
        if data.volume_m3 and data.volume_m3 > 0 and data.volume_m3 <= query.cargo_m3
    ]
    choices.sort(
        key=lambda entry: (entry[3] - entry[2]) / (entry[0].volume_m3 or Decimal(1)), reverse=True
    )
    if not choices:
        return [], True
    volumes = [
        float(data.volume_m3 / query.cargo_m3)
        for data, _, _, _ in choices
        if data.volume_m3 is not None
    ]
    matrix = [volumes]
    if query.budget is not None:
        matrix.append([float(cost / query.budget) for _, _, cost, _ in choices])
    result: Any = (
        milp(
            c=[-float(net - cost) for _, _, cost, net in choices],
            integrality=[1] * len(choices),
            bounds=Bounds(
                0,
                [
                    min(count, int(query.cargo_m3 // data.volume_m3))
                    for data, count, _, _ in choices
                    if data.volume_m3 is not None
                ],
            ),
            constraints=LinearConstraint(matrix, 0, 1),
            options={"time_limit": 10, "mip_rel_gap": 0.000001},
        )
        if run_solver
        else SimpleNamespace(x=None, status=1)
    )
    if not run_solver:
        result = SimpleNamespace(x=None, status=1)
    counts = (
        [
            max(0, min(bound, round(value)))
            for (_, bound, _, _), value in zip(choices, result.x, strict=True)
        ]
        if result.x is not None
        else [count for _, count, _, _ in choices]
    )
    # Recheck exact decimal limits; solver feasibility uses floating point tolerances.
    used, spent = Decimal(0), Decimal(0)
    totals: dict[int, CargoLine] = {}
    repaired = False
    for (data, _, cost, net), count in zip(choices, counts, strict=True):
        volume = data.volume_m3
        assert volume is not None
        allowed = min(count, int((query.cargo_m3 - used) // volume))
        if query.budget is not None:
            allowed = min(allowed, int((query.budget - spent) // cost))
        repaired |= allowed != count
        if allowed <= 0:
            continue
        used += volume * allowed
        spent += cost * allowed
        line = totals.setdefault(
            data.source.type_id,
            CargoLine(
                type_id=data.source.type_id,
                name=data.name or "Unknown item",
                quantity=0,
                cargo_m3=Decimal(0),
                investment=Decimal(0),
                revenue=Decimal(0),
                profit=Decimal(0),
            ),
        )
        line.quantity += allowed
        line.cargo_m3 += volume * allowed
        line.investment += cost * allowed
        line.revenue += net * allowed
        line.profit += (net - cost) * allowed
    return sorted(
        totals.values(), key=lambda line: line.profit, reverse=True
    ), result.status == 0 and not repaired


def solve_child(connection: Connection, inputs: list[TradeInput], query: CargoQuery) -> None:
    try:
        connection.send(optimize(inputs, query))
    finally:
        connection.close()


def bounded_optimize(inputs: list[TradeInput], query: CargoQuery) -> tuple[list[CargoLine], bool]:
    context = multiprocessing.get_context("spawn")
    parent, child = context.Pipe(duplex=False)
    process = context.Process(target=solve_child, args=(child, inputs, query))
    process.start()
    child.close()
    try:
        if parent.poll(15):
            try:
                result: tuple[list[CargoLine], bool] = parent.recv()
                return result
            except EOFError:
                pass
        return optimize(inputs, query, run_solver=False)
    finally:
        if process.is_alive():
            process.terminate()
        process.join(timeout=2)
        if process.is_alive():
            process.kill()
            process.join()
        parent.close()


class CargoService:
    def __init__(self, repository: TradingRepository, routes: TradingRoutes) -> None:
        self._repository, self._routes = repository, routes

    async def plan(self, query: CargoQuery) -> CargoResult:
        trading = TradingQuery(
            source_hub=query.source_hub,
            destination_hub=query.destination_hub,
            sell_price_range=query.sell_price_range,
            buy_price_range=query.buy_price_range,
            sales_tax=query.sales_tax,
            history_days=query.history_days,
            sale_side=query.sale_side,
            fresh_only=query.fresh_only,
        )
        inputs = await self._repository.inputs(trading)
        turnover = (
            await self._repository.turnover(
                trading, sorted({v.source.type_id for v in inputs}), datetime.now(UTC)
            )
            if query.filter_daily_turnover and query.min_daily_isk_volume is not None
            else {}
        )
        grouped: dict[str, list[TradeInput]] = defaultdict(list)
        missing = set()
        partial = False
        stale: dict[str, bool] = defaultdict(bool)
        for data in inputs:
            if data.name is not None and re.search(r"\bSKIN\b", data.name, re.IGNORECASE):
                continue
            if query.filter_daily_turnover and query.min_daily_isk_volume is not None:
                history = turnover.get(
                    (get_hub(data.destination.hub_id).region_id, data.source.type_id)
                )
                if history is None or history.daily_isk_volume < query.min_daily_isk_volume:
                    continue
            if data.volume_m3 is None or data.volume_m3 <= 0:
                missing.add(data.source.type_id)
                continue
            candidate = calculate_trade(data, trading, datetime.now(UTC))
            if candidate is None:
                continue
            partial |= data.source.sell_levels is None or data.destination.buy_levels is None
            stale[data.destination.hub_id] |= candidate.stale
            grouped[data.destination.hub_id].append(data)
        plans = []
        skipped = 0
        for hub in HUBS:
            if hub.hub_id == query.source_hub or (
                query.destination_hub is not None and hub.hub_id != query.destination_hub
            ):
                continue
            route = await self._routes.cached(query.source_hub, hub.hub_id, query.route_mode)
            if route.jumps is None or route.highsec is None:
                skipped += 1
                continue
            async with SOLVERS:
                lines, optimal = await asyncio.to_thread(
                    bounded_optimize, grouped[hub.hub_id], query
                )
            plans.append(
                CargoPlan(
                    destination_hub=hub.hub_id,
                    jumps=route.jumps,
                    highsec=route.highsec,
                    items=lines,
                    cargo_m3=sum((v.cargo_m3 for v in lines), Decimal(0)),
                    investment=sum((v.investment for v in lines), Decimal(0)),
                    revenue=sum((v.revenue for v in lines), Decimal(0)),
                    profit=sum((v.profit for v in lines), Decimal(0)),
                    optimal=optimal,
                    stale=stale[hub.hub_id],
                )
            )
        for plan in plans:
            plan.margin_pct = plan.profit / plan.investment * 100 if plan.investment else Decimal(0)
        plans.sort(key=lambda plan: plan.profit, reverse=True)
        return CargoResult(
            plans=plans, skipped_routes=skipped, missing_volume=len(missing), partial_depth=partial
        )
