from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock

import httpx
import pytest
from dishka import Provider, Scope, make_async_container

from app.domains.invention.models import PlanState
from app.domains.invention.repository import InventionRepository
from app.domains.invention.shopping import ShoppingService
from app.domains.manufacturing.repository import ManufacturingRepository
from app.main import create_app
from tests.domains.invention.test_invention import plan, settings
from tests.domains.market.test_market import price
from tests.helpers import make_settings


def market() -> AsyncMock:
    result = AsyncMock(spec=ManufacturingRepository)
    result.quotes.return_value = {
        34: price(34, sell_price="100"),
        34201: price(34201, sell_price="1"),
    }
    return result


@pytest.mark.parametrize(
    ("units", "runs", "copies", "capacity", "attempts"),
    [
        (1, 1, 1, 50000, 3),
        (5000, 1, 1, 50000, 3),
        (50000, 10, 1, 50000, 3),
        (50001, 11, 2, 100000, 5),
    ],
)
async def test_ammunition_output_and_whole_successful_copies(
    units: int, runs: int, copies: int, capacity: int, attempts: int
) -> None:
    repository = AsyncMock(spec=InventionRepository)
    now = datetime.now(UTC)
    repository.plan.return_value = PlanState(
        key=settings().plan_key,
        plans=[plan(units_per_run=5000)],
        synced_at=now,
        expires_at=now + timedelta(days=1),
    )
    result = await ShoppingService(repository, market()).plan(10, units)
    assert result.status == "ready"
    option = result.options[0]
    assert option.runs_per_copy == 10
    assert option.units_per_run == 5000
    assert option.manufacturing_runs == runs
    assert option.successful_copies == copies
    assert option.output_capacity == capacity
    assert option.attempts == attempts
    assert option.materials[0].quantity == attempts * 2
    assert result.science_level == result.encryption_level == 2
    assert option.probability < repository.plan.return_value.plans[0].probability
    repository.plan.assert_awaited_once_with(settings().plan_key)


async def test_missing_unsupported_stale_and_decryptor_materials() -> None:
    repository = AsyncMock(spec=InventionRepository)
    service = ShoppingService(repository, market())
    repository.plan.return_value = None
    assert (await service.plan(10, 1)).status == "not_prepared"
    now = datetime.now(UTC)
    state = PlanState(
        key=settings().plan_key, plans=[], synced_at=now, expires_at=now - timedelta(days=1)
    )
    repository.plan.return_value = state
    assert (await service.plan(10, 1)).status == "unsupported"
    state.plans = [
        plan(
            decryptor_id=34201,
            decryptor_name="Accelerant",
            materials=[{"type_id": 34, "quantity": 2}, {"type_id": 34201, "quantity": 1}],
        )
    ]
    result = await service.plan(10, 1)
    assert result.stale
    assert result.options[0].materials[1].quantity == result.options[0].attempts


async def test_shopping_api_and_page() -> None:
    repository = AsyncMock(spec=InventionRepository)
    repository.plan.return_value = None
    service = ShoppingService(repository, market())
    provider = Provider(scope=Scope.REQUEST)
    provider.provide(lambda: service, provides=ShoppingService)
    container = make_async_container(provider)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(create_app(container, make_settings())),
        base_url="http://test",
    ) as client:
        assert (await client.get("/invention-shopping")).status_code == 200
        result = await client.get("/api/v1/invention/shopping/10?units=5001")
        assert result.status_code == 200
        assert result.json()["desired_units"] == 5001
        for units in ("0", "-1", "1.5", "1000000001"):
            assert (
                await client.get("/api/v1/invention/shopping/10", params={"units": units})
            ).status_code == 422
    await container.close()


async def test_expensive_decryptor_can_reduce_total_invention_budget() -> None:
    repository = AsyncMock(spec=InventionRepository)
    now = datetime.now(UTC)
    repository.plan.return_value = PlanState(
        key=settings().plan_key,
        plans=[
            plan(),
            plan(
                decryptor_id=34201,
                decryptor_name="Accelerant",
                runs_per_copy=20,
                probability="0.6",
                materials=[{"type_id": 34, "quantity": 2}, {"type_id": 34201, "quantity": 1}],
            ),
        ],
        synced_at=now,
        expires_at=now + timedelta(days=1),
    )
    quotes = market()
    quotes.quotes.return_value[34201].sell_price = Decimal(100)
    service = ShoppingService(repository, quotes)
    result = await service.plan(10, 1000)
    assert result.best is not None
    assert result.best.decryptor_id == 34201
    assert result.best.estimated_cost is not None
    assert result.options[0].estimated_cost is not None
    assert result.best.estimated_cost < result.options[0].estimated_cost
    quotes.quotes.return_value[34201].sell_price = Decimal(10000)
    expensive = await service.plan(10, 1000)
    assert expensive.best is not None
    assert expensive.best.decryptor_id is None
    quotes.quotes.return_value[34201].sell_price = None
    partial = await service.plan(10, 1000)
    assert not partial.complete_pricing
    assert partial.options[1].missing_prices == [34201]
    quotes.quotes.return_value = {}
    assert (await service.plan(10, 1000)).best is None
