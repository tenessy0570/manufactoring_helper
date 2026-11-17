import asyncio
import copy
import json
from collections.abc import AsyncIterator
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import httpx
import pytest
import respx
from arq.connections import ArqRedis
from dishka import Provider, Scope, make_async_container
from fakeredis import FakeAsyncRedis
from pydantic import TypeAdapter
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core.cache import CacheService, MemoryCache
from app.core.orm import Base
from app.core.repository import SQLAlchemyUnitOfWork
from app.domains.history.repository import SQLHistoryRepository
from app.domains.invention.calculation import price_plans
from app.domains.invention.gateway import EverefInventionGateway, InventionGateway
from app.domains.invention.models import (
    InventionPlan,
    InventionQuery,
    InventionRequest,
    InventionSettings,
    PlanState,
)
from app.domains.invention.queue import InventionQueue, RedisInventionQueue
from app.domains.invention.repository import InventionRepository, SQLInventionRepository
from app.domains.invention.service import InventionService, InventionSyncService
from app.domains.manufacturing.gateway import IndustryClient
from app.domains.manufacturing.models import ManufacturingQuery
from app.domains.manufacturing.repository import ManufacturingRepository
from app.domains.manufacturing.service import ManufacturingService
from app.main import create_app
from tests.domains.catalog.test_catalog import NOW
from tests.domains.manufacturing.test_manufacturing import seed
from tests.domains.market.test_market import price
from tests.helpers import make_settings

EXPIRES = NOW + timedelta(days=7)


def settings(**kwargs: Any) -> InventionSettings:
    return InventionSettings.model_validate({"type_id": 10, **kwargs})


def plan(**kwargs: Any) -> InventionPlan:
    return InventionPlan.model_validate(
        {
            "decryptor_id": None,
            "decryptor_name": "None",
            "source_blueprint_id": 11,
            "invented_blueprint_id": 12,
            "probability": "0.5",
            "runs_per_copy": 10,
            "units_per_run": 2,
            "materials": [{"type_id": 34, "quantity": "2"}],
            "job_cost_per_attempt": "10",
            "me": 2,
            "te": 4,
            **kwargs,
        }
    )


def request(**kwargs: Any) -> InventionRequest:
    selected = settings()
    result = price_plans([plan()], {34: price(34, buy_price="90", sell_price="100")}, selected)
    return InventionRequest.model_validate(
        {
            "key": selected.key,
            "settings": selected,
            "result": result,
            "status": "ready",
            "updated_at": NOW,
            "expires_at": NOW + timedelta(minutes=5),
            **kwargs,
        }
    )


def test_keys_ignore_legacy_skills_and_fees_but_separate_hub_and_side() -> None:
    assert settings(broker_fee="0.00").key == settings(broker_fee="99").key == settings().key
    assert "broker_fee" not in settings(broker_fee="99").model_dump()
    for kwargs in (
        {"hub_id": "amarr"},
        {"order_type": "buy"},
    ):
        assert settings(**kwargs).key != settings().key
    assert settings(hub_id="amarr", order_type="buy").plan_key == settings().plan_key
    assert settings(science_level=4, encryption_level=0).plan_key == settings().plan_key
    assert settings(science_level=4, encryption_level=0).key == settings().key
    assert "science_level" not in settings(science_level=4).model_dump()
    assert "encryption_level" not in settings(encryption_level=0).model_dump()


def test_expected_cost_uses_attempts_probability_runs_and_output_quantity() -> None:
    result = price_plans([plan()], {34: price(34, sell_price="100", buy_price="90")}, settings())
    assert result.best is not None
    assert result.best.cost_per_attempt == 200
    assert result.best.expected_cost_per_unit == 20
    bought = price_plans(
        [plan()], {34: price(34, buy_price="90")}, settings(order_type="buy", broker_fee="10")
    )
    assert bought.best is not None
    assert bought.best.expected_cost_per_unit == Decimal("18")
    missing = price_plans([plan()], {}, settings())
    assert missing.best is None
    assert missing.options[0].missing_prices == [34]
    assert not missing.complete_pricing
    assert result.price_fingerprint != bought.price_fingerprint


def test_compares_decryptors_and_does_not_apply_me_te_to_manufacturing() -> None:
    options = [
        plan(),
        plan(
            decryptor_id=34201,
            decryptor_name="Accelerant",
            runs_per_copy=20,
            me=99,
            te=99,
            materials=[{"type_id": 34, "quantity": 2}, {"type_id": 34201, "quantity": 1}],
        ),
    ]
    result = price_plans(
        options, {34: price(34, sell_price="100"), 34201: price(34201, sell_price="1")}, settings()
    )
    assert result.best is not None
    assert result.best.plan.decryptor_name == "Accelerant"
    assert result.best.expected_cost_per_unit == Decimal("10.05")


def test_captured_public_data_matches_expected_unit_cost_and_decryptors() -> None:
    plans = TypeAdapter(list[InventionPlan]).validate_json(
        Path("tests/fixtures/invention-plans.json").read_text(encoding="utf-8")
    )
    raw = json.loads(
        Path("tests/fixtures/invention.json").read_text(encoding="utf-8"), parse_float=Decimal
    )
    source = raw["invention"]["2457"]
    quotes = {
        material["type_id"]: price(material["type_id"], sell_price=material["cost_per_unit"])
        for material in source["materials"].values()
    }
    result = price_plans([plans[0]], quotes, settings())
    assert result.best is not None
    material_only = source["total_material_cost"] / source["expected_units"]
    assert abs(result.best.expected_cost_per_unit - material_only) < Decimal("0.01")
    assert len(plans) == 9
    for option in plans[1:]:
        assert any(material.type_id == option.decryptor_id for material in option.materials)
    ammo = plan(units_per_run=5000)
    result = price_plans([ammo], {34: price(34, sell_price="100")}, settings())
    assert result.best is not None
    assert result.best.expected_cost_per_unit == Decimal("0.008")


@pytest.fixture
async def session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with AsyncSession(engine, expire_on_commit=False) as session:
        yield session
    await engine.dispose()


async def test_persistent_cache_survives_sessions_and_duplicate_prepare(
    session: AsyncSession,
) -> None:
    repository = SQLInventionRepository(session)
    state = PlanState(key=settings().plan_key, plans=[plan()], synced_at=NOW, expires_at=EXPIRES)
    assert await repository.plan(state.key) is None
    await repository.save_plan(state)
    await repository.ensure_request(request(status="pending", result=None))
    await repository.save_request(request())
    await repository.ensure_request(request(status="pending", result=None))
    await session.commit()
    assert (await repository.requests([settings().key]))[settings().key] == request()
    async with AsyncSession(session.bind) as second:
        restored = SQLInventionRepository(second)
        assert await restored.plan(state.key) == state
        assert (await restored.requests([settings().key]))[
            settings().key
        ].result == request().result
        assert await restored.active_settings() == [settings()]
    await repository.save_request(request(status="error", expires_at=NOW))
    await session.rollback()
    assert (await repository.requests([settings().key]))[settings().key].status == "ready"


async def test_request_api_queues_without_running_expensive_gateway(session: AsyncSession) -> None:
    repository = SQLInventionRepository(session)
    queue = AsyncMock(spec=InventionQueue)
    queue.enqueue.return_value = True
    service = InventionService(
        repository, queue, SQLAlchemyUnitOfWork(session), CacheService(MemoryCache(10)), lambda: NOW
    )
    assert (await service.view(settings())).request is None
    view = await service.prepare(settings())
    assert view.queued
    assert view.request is not None
    assert view.request.status == "pending"
    await repository.save_request(request())
    await session.commit()
    queue.reset_mock()
    assert not (await service.prepare(settings())).queued
    queue.enqueue.assert_not_awaited()
    assert not (await service.view(settings())).stale
    await repository.save_request(request(expires_at=NOW))
    await session.commit()
    assert (await service.view(settings())).stale


async def test_source_is_cached_across_hubs_and_repricing_never_refetches(
    session: AsyncSession,
) -> None:
    repository = SQLInventionRepository(session)
    gateway = AsyncMock(spec=InventionGateway)
    gateway.fetch.return_value = [plan()]
    manufacturing = AsyncMock(spec=ManufacturingRepository)
    manufacturing.quotes.return_value = {34: price(34, sell_price="100")}
    service = InventionSyncService(
        repository, gateway, manufacturing, SQLAlchemyUnitOfWork(session), clock=lambda: NOW
    )
    first = await service.sync(settings())
    assert first.result is not None
    assert first.result.best is not None
    assert first.result.best.expected_cost_per_unit == 20
    await service.sync(settings(broker_fee="15"))
    gateway.fetch.assert_awaited_once()
    manufacturing.quotes.assert_awaited_once()
    await service.sync(settings(hub_id="amarr"))
    gateway.fetch.assert_awaited_once()
    manufacturing.quotes.return_value = {34: price(34, sell_price="200", expires_at=EXPIRES)}
    later = InventionSyncService(
        repository,
        gateway,
        manufacturing,
        SQLAlchemyUnitOfWork(session),
        clock=lambda: NOW + timedelta(days=1),
    )
    result = await later.sync(settings())
    gateway.fetch.assert_awaited_once()
    assert result.result is not None
    assert result.result.best is not None
    assert result.result.best.expected_cost_per_unit == 40
    assert result.result.price_fingerprint != first.result.price_fingerprint
    await later.record_error(settings(), "ConnectionError")
    failed = (await repository.requests([settings().key]))[settings().key]
    assert failed.status == "error"
    assert failed.result == result.result


async def test_empty_and_missing_price_states(session: AsyncSession) -> None:
    repository = SQLInventionRepository(session)
    gateway = AsyncMock(spec=InventionGateway)
    manufacturing = AsyncMock(spec=ManufacturingRepository)
    manufacturing.quotes.return_value = {}
    gateway.fetch.return_value = []
    service = InventionSyncService(
        repository, gateway, manufacturing, SQLAlchemyUnitOfWork(session), clock=lambda: NOW
    )
    assert (await service.sync(settings())).status == "unsupported"
    gateway.fetch.return_value = [plan()]
    assert (await service.sync(settings(type_id=20))).status == "missing_prices"


async def test_failed_source_refresh_keeps_durable_plan(session: AsyncSession) -> None:
    repository = SQLInventionRepository(session)
    old = PlanState(
        key=settings().plan_key, plans=[plan()], synced_at=NOW - timedelta(days=8), expires_at=NOW
    )
    await repository.save_plan(old)
    await repository.save_request(request(expires_at=NOW))
    await session.commit()
    gateway = AsyncMock(spec=InventionGateway)
    gateway.fetch.side_effect = ConnectionError("offline")
    service = InventionSyncService(
        repository,
        gateway,
        AsyncMock(spec=ManufacturingRepository),
        SQLAlchemyUnitOfWork(session),
        clock=lambda: NOW,
    )
    with pytest.raises(ConnectionError, match="offline"):
        await service.sync(settings())
    assert await repository.plan(settings().plan_key) == old
    assert (await repository.requests([settings().key]))[settings().key].result == request().result
    await service.record_error(settings(hub_id="hek"), "ConnectionError")
    assert (await repository.requests([settings(hub_id="hek").key]))[
        settings(hub_id="hek").key
    ].status == "error"


async def test_source_and_valuation_write_failures_roll_back() -> None:
    repository = AsyncMock(spec=InventionRepository)
    repository.requests.return_value = {}
    repository.plan.return_value = None
    repository.save_plan.side_effect = RuntimeError("source write failed")
    gateway = AsyncMock(spec=InventionGateway)
    gateway.fetch.return_value = [plan()]
    prices = AsyncMock(spec=ManufacturingRepository)
    prices.quotes.return_value = {34: price(34)}
    uow = AsyncMock(spec=SQLAlchemyUnitOfWork)
    service = InventionSyncService(repository, gateway, prices, uow, clock=lambda: NOW)
    with pytest.raises(RuntimeError, match="source write failed"):
        await service.sync(settings())
    uow.rollback.assert_awaited_once()
    uow.reset_mock()
    repository.plan.return_value = PlanState(
        key=settings().plan_key, plans=[plan()], synced_at=NOW, expires_at=EXPIRES
    )
    repository.save_request.side_effect = RuntimeError("result write failed")
    with pytest.raises(RuntimeError, match="result write failed"):
        await service.sync(settings())
    uow.rollback.assert_awaited_once()


async def test_gateway_normalizes_scaled_attempts_and_fails_atomically() -> None:
    fixture = json.loads(
        await asyncio.to_thread(Path("tests/fixtures/invention.json").read_text, encoding="utf-8")
    )
    async with httpx.AsyncClient(base_url="https://test") as http:
        gateway = EverefInventionGateway(IndustryClient(http, 3, 0))
        with respx.mock:
            route = respx.get("https://test/v1/industry/cost").respond(200, json=fixture)
            plans = await gateway.fetch(settings(type_id=2456))
            assert len(plans) == 9
            assert plans[0].materials[0].quantity == 1
            assert plans[0].source_blueprint_id == 2455
            assert plans[0].invented_blueprint_id == 2457
            assert plans[0].runs_per_copy == 10
            assert route.call_count == 9
            assert route.calls[0].request.url.params["amarr_encryption_methods"] == "4"
            assert route.calls[0].request.url.params["mechanical_engineering"] == "5"
            invalid = copy.deepcopy(fixture)
            invalid["manufacturing"] = {}
            route.respond(200, json=invalid)
            with pytest.raises(ValueError, match="link invention"):
                await gateway.fetch(settings(type_id=2456))
            invalid["invention"] = {}
            route.respond(200, json=invalid)
            assert await gateway.fetch(settings(type_id=2456)) == []
            route.respond(
                400,
                json={
                    "message": (
                        "ClientException: Product type ID 2456 is not produced from a blueprint"
                    )
                },
            )
            assert await gateway.fetch(settings(type_id=2456)) == []
            route.respond(503)
            with pytest.raises(Exception, match="503"):
                await gateway.fetch(settings(type_id=2456))


async def test_queue_deduplicates_by_full_request_key() -> None:
    redis = AsyncMock()
    queue = RedisInventionQueue(redis)
    assert await queue.enqueue(settings())
    assert redis.enqueue_job.await_args is not None
    first = redis.enqueue_job.await_args.kwargs["_job_id"]
    await queue.enqueue(settings(hub_id="amarr"))
    assert redis.enqueue_job.await_args.kwargs["_job_id"] != first
    redis.enqueue_job.return_value = None
    assert not await queue.enqueue(settings())
    assert not await queue.enqueue_catalog(InventionQuery())


async def test_arq_binary_queue_actually_deduplicates_jobs() -> None:
    fake = FakeAsyncRedis(decode_responses=False)
    redis = ArqRedis(pool_or_conn=fake.connection_pool)
    queue = RedisInventionQueue(redis)
    try:
        assert await queue.enqueue(settings())
        assert not await queue.enqueue(settings())
        assert await queue.enqueue(settings(hub_id="amarr"))
        assert await queue.enqueue_catalog()
        assert not await queue.enqueue_catalog()
    finally:
        await redis.aclose()
        await fake.aclose()


async def test_manufacturing_deducts_cached_unit_cost_before_ranking(session: AsyncSession) -> None:
    manufacturing = await seed(session)
    repository = SQLInventionRepository(session)
    cached = request()
    await repository.save_request(cached)
    service = ManufacturingService(
        manufacturing, SQLHistoryRepository(session), lambda: NOW, invention=repository
    )
    page = await service.opportunities(
        ManufacturingQuery(type_ids=[10], include_invention_cost=True)
    )
    assert page.items[0].invention_cost_per_unit == 20
    assert page.items[0].profit_per_unit == -7
    assert page.items[0].invention_included
    assert page.items[0].invention_status == "ready"
    page = await service.opportunities(
        ManufacturingQuery(type_ids=[10, 20], include_invention_cost=True, min_profit=Decimal(0))
    )
    assert page.total == 0
    assert page.missing_invention == 1
    page = await service.opportunities(
        ManufacturingQuery(type_ids=[10], include_invention_cost=False)
    )
    assert page.items[0].profit_per_unit == 13
    await repository.save_request(request(expires_at=NOW))
    stale = await service.opportunities(
        ManufacturingQuery(type_ids=[10], include_invention_cost=True)
    )
    assert stale.items[0].invention_status == "stale"
    assert stale.items[0].stale
    assert (
        await service.opportunities(
            ManufacturingQuery(type_ids=[10], include_invention_cost=True, fresh_only=True)
        )
    ).total == 0


async def test_api_reads_and_schedules_cached_work(session: AsyncSession) -> None:
    repository = SQLInventionRepository(session)
    queue = AsyncMock(spec=InventionQueue)
    queue.enqueue.return_value = True
    queue.enqueue_catalog.return_value = True
    service = InventionService(
        repository, queue, SQLAlchemyUnitOfWork(session), CacheService(MemoryCache(10)), lambda: NOW
    )
    provider = Provider(scope=Scope.REQUEST)
    provider.provide(lambda: service, provides=InventionService)
    provider.provide(lambda: queue, provides=InventionQueue)
    container = make_async_container(provider)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(
            create_app(container=container, settings=make_settings(), require_login=False)
        ),
        base_url="http://test",
    ) as client:
        assert (await client.get("/api/v1/invention/10")).json()["request"] is None
        assert (await client.post("/api/v1/invention/10/prepare")).status_code == 202
        assert (await client.post("/api/v1/invention/prepare?hub_id=amarr")).status_code == 202
        assert (await client.get("/api/v1/invention/10?science_level=6")).status_code == 200
    await container.close()


def test_default_valuation_key_keeps_existing_prepared_cache() -> None:
    import hashlib

    previous = settings().model_dump(mode="json")
    previous.update(science_level=5, encryption_level=4)
    previous["broker_fee"] = "0"
    expected = hashlib.sha256(json.dumps(previous, sort_keys=True).encode()).hexdigest()
    assert settings().key == expected
    assert settings().plan_key == f"v1:{settings().type_id}:5:4"


async def test_daily_valuation_does_not_repeat_when_market_quotes_expire(
    session: AsyncSession,
) -> None:
    repository = SQLInventionRepository(session)
    gateway = AsyncMock(spec=InventionGateway)
    gateway.fetch.return_value = [plan()]
    manufacturing = AsyncMock(spec=ManufacturingRepository)
    manufacturing.quotes.return_value = {34: price(34, expires_at=NOW - timedelta(minutes=1))}
    service = InventionSyncService(
        repository, gateway, manufacturing, SQLAlchemyUnitOfWork(session), clock=lambda: NOW
    )
    first = await service.sync(settings())
    assert first.expires_at == NOW.replace(hour=12, minute=30)
    later = InventionSyncService(
        repository,
        gateway,
        manufacturing,
        SQLAlchemyUnitOfWork(session),
        clock=lambda: NOW + timedelta(hours=11),
    )
    assert await later.sync(settings()) == first
    manufacturing.quotes.assert_awaited_once()
    gateway.fetch.assert_awaited_once()


async def test_valuation_expires_at_next_daily_refresh_not_after_job_finish(
    session: AsyncSession,
) -> None:
    repository = SQLInventionRepository(session)
    gateway = AsyncMock(spec=InventionGateway)
    gateway.fetch.return_value = [plan()]
    manufacturing = AsyncMock(spec=ManufacturingRepository)
    manufacturing.quotes.return_value = {34: price(34)}
    service = InventionSyncService(
        repository,
        gateway,
        manufacturing,
        SQLAlchemyUnitOfWork(session),
        clock=lambda: NOW.replace(hour=12, minute=33),
    )
    result = await service.sync(settings())
    assert result.expires_at == (NOW + timedelta(days=1)).replace(hour=12, minute=30)


async def test_migration_merges_fee_variants_and_reuses_tax_free_cache_without_source_calls(
    session: AsyncSession,
) -> None:
    import runpy

    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import insert, select
    from sqlalchemy.engine import Connection

    from app.domains.invention.tables import InventionRequestTable

    repository = SQLInventionRepository(session)
    source_plan = PlanState(
        key=settings().plan_key, plans=[plan()], synced_at=NOW, expires_at=EXPIRES
    )
    await repository.save_plan(source_plan)
    for fee, total in (("10", "208"), ("20", "226")):
        row = request().model_dump(mode="json")
        row.update(
            key="legacy-fee-" + fee,
            settings={"type_id": 10, "hub_id": "jita", "order_type": "buy", "broker_fee": fee},
            updated_at=NOW,
            expires_at=EXPIRES,
        )
        assert row["result"] is not None
        option = row["result"]["options"][0]
        option["cost_per_attempt"] = total
        option["expected_cost_per_unit"] = str(Decimal(total) / 10)
        row["result"]["best"] = option
        await session.execute(insert(InventionRequestTable).values(**row))
    empty = request(key="pending", result=None, status="pending", settings=settings(hub_id="amarr"))
    await repository.save_request(empty)
    await session.commit()
    migration = runpy.run_path("alembic/versions/0009_tax_free_invention.py")

    def upgrade(connection: Connection) -> None:
        with Operations.context(MigrationContext.configure(connection)):
            migration["upgrade"]()

    await (await session.connection()).run_sync(upgrade)
    await session.commit()
    rows = list(await session.scalars(select(InventionRequestTable)))
    assert len(rows) == 2
    canonical = (await repository.requests([settings(order_type="buy").key]))[
        settings(order_type="buy").key
    ]
    assert canonical.result is not None
    assert canonical.result.best is not None
    assert canonical.result.best.cost_per_attempt == 180
    assert canonical.result.best.expected_cost_per_unit == 18
    assert canonical.expires_at == EXPIRES
    assert await repository.plan(source_plan.key) == source_plan
    gateway = AsyncMock(spec=InventionGateway)
    quotes = AsyncMock(spec=ManufacturingRepository)
    sync = InventionSyncService(
        repository, gateway, quotes, SQLAlchemyUnitOfWork(session), clock=lambda: NOW
    )
    assert await sync.sync(settings(order_type="buy", broker_fee="99")) == canonical
    gateway.fetch.assert_not_awaited()
    quotes.quotes.assert_not_awaited()
