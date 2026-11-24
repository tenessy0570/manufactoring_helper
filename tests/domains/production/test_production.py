from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import httpx
import pytest
from dishka import Provider, Scope, make_async_container
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core.application_errors import ErrorKind
from app.core.orm import Base
from app.core.repository import SQLAlchemyUnitOfWork, UnitOfWork
from app.domains.accounts.service import AccountService
from app.domains.catalog.repository import ItemTypeRepository
from app.domains.invention.models import PlanState
from app.domains.invention.repository import InventionRepository
from app.domains.invention.shopping import ShoppingService
from app.domains.manufacturing.repository import ManufacturingRepository
from app.domains.production.errors import ProductionError
from app.domains.production.models import (
    EntryInput,
    Estimate,
    EstimateInput,
    Production,
    ProductionCreate,
    ProductionDetails,
    PurchaseListInput,
)
from app.domains.production.repository import ProductionRepository, SQLProductionRepository
from app.domains.production.service import (
    ProductionEstimateService,
    ProductionService,
)
from app.main import create_app
from tests.domains.accounts.test_accounts import Limiter, make_user
from tests.domains.catalog.test_catalog import item
from tests.domains.invention.test_invention import plan, settings
from tests.domains.manufacturing.test_manufacturing import recipe, recipe_state
from tests.domains.market.test_market import price
from tests.helpers import make_settings


class MemoryProductionRepository(ProductionRepository):
    def __init__(self) -> None:
        self.items: dict[UUID, Production] = {}

    async def find(self, user_id: UUID, offset: int, limit: int) -> list[Production]:
        return [row.model_copy(deep=True) for row in self.items.values() if row.user_id == user_id][
            offset : offset + limit
        ]

    async def get(
        self, user_id: UUID, production_id: UUID, lock: bool = False
    ) -> Production | None:
        row = self.items.get(production_id)
        return row.model_copy(deep=True) if row is not None and row.user_id == user_id else None

    async def save(self, production: Production) -> None:
        self.items[production.id] = production.model_copy(deep=True)

    async def delete(self, user_id: UUID, production_id: UUID) -> None:
        del self.items[production_id]


def service(repository: ProductionRepository | None = None) -> ProductionService:
    catalog = AsyncMock(spec=ItemTypeRepository)
    catalog.find.return_value = [item(10)]
    return ProductionService(
        repository or MemoryProductionRepository(), catalog, AsyncMock(spec=UnitOfWork)
    )


async def test_empty_progressive_expenses_partial_sales_and_corrections() -> None:
    svc = service()
    user = uuid4()
    row = await svc.create(user, ProductionCreate(type_id=10))
    assert row.units is None
    assert row.entries == []
    assert row.totals["invention"] is None
    assert row.totals["balance"] == 0
    for kind, amount in [
        ("invention", "0"),
        ("materials", "100"),
        ("manufacturing", "20"),
        ("income", "50"),
        ("income", "90"),
    ]:
        row = await svc.entry(
            user, row.id, EntryInput.model_validate({"kind": kind, "amount": amount})
        )
    assert row.totals["invention"] == 0
    assert row.totals["income"] == 140
    assert row.totals["balance"] == 20
    saved = await svc.update(
        user, row.id, ProductionDetails(units=1000, comment="More units", status="completed")
    )
    assert saved.entries == row.entries
    assert saved.units == 1000
    assert saved.status == "completed"
    saved = await svc.entry(
        user, row.id, EntryInput(kind="income", amount=Decimal("80.01")), row.entries[-1].id
    )
    assert saved.totals["income"] == Decimal("130.01")
    assert saved.totals["margin"] == Decimal("10.01") / 120 * 100
    saved = await svc.delete_entry(user, row.id, row.entries[0].id)
    assert saved.totals["invention"] is None
    assert len(await svc.find(user)) == 1
    assert await svc.find(uuid4()) == []
    for operation in [
        svc.get(uuid4(), row.id),
        svc.update(uuid4(), row.id, ProductionDetails()),
        svc.entry(uuid4(), row.id, EntryInput(kind="income", amount=Decimal(1))),
        svc.delete(uuid4(), row.id),
        svc.delete_entry(user, row.id, uuid4()),
        svc.entry(user, row.id, EntryInput(kind="income", amount=Decimal(1)), uuid4()),
    ]:
        with pytest.raises(ProductionError) as error:
            await operation
        assert error.value.kind == ErrorKind.NOT_FOUND
    await svc.delete(user, row.id)
    assert await svc.find(user) == []


async def test_invalid_catalog_and_transaction_failures() -> None:
    svc = service()
    assert isinstance(svc.catalog, AsyncMock)
    svc.catalog.find.return_value = []
    with pytest.raises(ProductionError):
        await svc.create(uuid4(), ProductionCreate(type_id=10))
    svc.catalog.find.return_value = [item(10)]
    assert isinstance(svc.uow, AsyncMock)
    svc.uow.commit.side_effect = RuntimeError("commit failed")
    with pytest.raises(RuntimeError):
        await svc.create(uuid4(), ProductionCreate(type_id=10))
    svc.uow.rollback.assert_awaited_once()
    svc.uow.commit.side_effect = None
    row = await svc.create(uuid4(), ProductionCreate(type_id=10))
    svc.uow.commit.side_effect = RuntimeError("commit failed")
    with pytest.raises(RuntimeError):
        await svc.delete(row.user_id, row.id)
    assert svc.uow.rollback.await_count == 2


@pytest.mark.parametrize("amount", ["-1", "0.001", "NaN", "Infinity", "1000000000000000001"])
def test_amount_validation(amount: str) -> None:
    with pytest.raises(ValidationError):
        EntryInput.model_validate({"kind": "income", "amount": amount})


async def test_estimates_whole_runs_fees_missing_data_and_invention() -> None:
    svc = service()
    row = await svc.create(uuid4(), ProductionCreate(type_id=10))
    market = AsyncMock(spec=ManufacturingRepository)
    market.recipes.return_value = {10: recipe_state(recipe=recipe(units=5000))}
    market.quotes.return_value = {34: price(34, buy_price="2", sell_price="3")}
    invention = AsyncMock(spec=InventionRepository)
    invention.plan.return_value = None
    estimator = ProductionEstimateService(svc, market, ShoppingService(invention, market))

    async def estimate(**values: object) -> Estimate:
        return await estimator.estimate(
            row.user_id, row.id, EstimateInput.model_validate({"units": 5001, **values})
        )

    result = await estimate(kind="materials")
    assert result.amount == 60
    assert "2 runs" in result.description
    assert (
        await estimate(kind="materials", material_order_type="buy", buy_broker_fee="10")
    ).amount == 44
    assert (
        await estimate(kind="manufacturing", facility_tax="1", system_cost_index="2")
    ).amount == 14
    market.recipes.return_value = {
        10: recipe_state(recipe=recipe(units=5000, estimated_item_value=None))
    }
    assert (await estimate(kind="manufacturing")).amount == 8
    with pytest.raises(ProductionError):
        await estimate(kind="manufacturing", facility_tax="1")
    market.quotes.return_value = {}
    with pytest.raises(ProductionError):
        await estimate(kind="materials")
    market.recipes.return_value = {}
    with pytest.raises(ProductionError):
        await estimate(kind="manufacturing")
    with pytest.raises(ProductionError):
        await estimate(kind="invention")
    now = datetime.now(UTC)
    invention.plan.return_value = PlanState(
        key=settings().plan_key,
        plans=[plan(units_per_run=5000)],
        synced_at=now,
        expires_at=now - timedelta(days=1),
    )
    market.quotes.return_value = {34: price(34, sell_price="100")}
    result = await estimate(kind="invention")
    assert result.amount == 600
    assert result.stale
    assert "3 expected attempts" in result.description
    assert (await svc.get(row.user_id, row.id)).entries == []


@pytest.fixture
async def sql_services() -> AsyncIterator[tuple[ProductionService, AccountService]]:
    from app.domains.accounts.repository import SQLAccountRepository

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with AsyncSession(engine, expire_on_commit=False) as session:
        svc = service(SQLProductionRepository(session))
        svc.uow = SQLAlchemyUnitOfWork(session)
        yield svc, AccountService(SQLAccountRepository(session), svc.uow, Limiter())
    await engine.dispose()


async def test_authenticated_api_ownership_and_sql_roundtrip(
    sql_services: tuple[ProductionService, AccountService],
) -> None:
    svc, accounts = sql_services
    first = await make_user(accounts, "first", False)
    second = await make_user(accounts, "second", True)
    provider = Provider(scope=Scope.REQUEST)
    provider.provide(lambda: svc, provides=ProductionService)
    provider.provide(lambda: accounts, provides=AccountService)
    market = AsyncMock(spec=ManufacturingRepository)
    market.recipes.return_value = {10: recipe_state()}
    estimator = ProductionEstimateService(svc, market, AsyncMock(spec=ShoppingService))
    provider.provide(lambda: estimator, provides=ProductionEstimateService)
    container = make_async_container(provider)
    headers = {"X-Requested-With": "XMLHttpRequest"}
    from app.domains.accounts.models import Credentials

    _, token = await accounts.login(
        Credentials.model_validate({"username": "first", "password": "test-password-for-tests"}),
        "test",
    )
    _, second_token = await accounts.login(
        Credentials.model_validate({"username": "second", "password": "test-password-for-tests"}),
        "test",
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(create_app(container, make_settings())),
        base_url="http://test",
    ) as client:
        assert (await client.get("/production-history")).status_code == 303
        assert (await client.get("/api/v1/productions")).status_code == 401
        client.cookies.set("eve_session", token)
        assert (await client.get("/production-history")).status_code == 200
        created = await client.post("/api/v1/productions", json={"type_id": 10}, headers=headers)
        assert created.status_code == 201
        row = created.json()
        identifier = row["id"]
        assert row["user_id"] == str(first.id)
        path = "/api/v1/productions/" + identifier
        assert (await client.get(path)).status_code == 200
        assert len((await client.get("/api/v1/productions")).json()) == 1
        assert (
            await client.put(
                path,
                json={"units": 200, "actual_units": 175, "actual_runs": 3, "comment": "batch"},
                headers=headers,
            )
        ).status_code == 200
        persisted = (await client.get(path)).json()
        assert persisted["units"] == 200
        assert persisted["actual_units"] == 175
        assert persisted["actual_runs"] == 3
        purchases = await client.post(
            path + "/purchase-list", json={"kind": "materials", "units": 3}, headers=headers
        )
        assert purchases.status_code == 200
        assert purchases.json()["materials"] == [{"type_id": 34, "quantity": 20}]
        added = await client.post(
            path + "/entries", json={"kind": "income", "amount": "1.23"}, headers=headers
        )
        entry_id = added.json()["entries"][0]["id"]
        assert added.json()["totals"]["income"] == "1.23"
        assert (
            await client.put(
                path + "/entries/" + entry_id,
                json={"kind": "income", "amount": "5"},
                headers=headers,
            )
        ).status_code == 200
        assert (
            await client.post(
                path + "/estimate", json={"kind": "manufacturing", "units": 3}, headers=headers
            )
        ).json()["amount"] == "8.00"
        assert (
            await client.post(
                path + "/entries", json={"kind": "income", "amount": "-1"}, headers=headers
            )
        ).status_code == 422
        client.cookies.set("eve_session", second_token)
        assert second.is_superuser
        assert (await client.get("/api/v1/productions")).json() == []
        for method, suffix, body in [
            ("GET", "", None),
            ("PUT", "", {}),
            ("DELETE", "", None),
            ("POST", "/entries", {"kind": "income", "amount": "1"}),
            ("PUT", "/entries/" + entry_id, {"kind": "income", "amount": "1"}),
            ("DELETE", "/entries/" + entry_id, None),
            ("POST", "/estimate", {"kind": "manufacturing", "units": 1}),
            ("POST", "/purchase-list", {"kind": "materials", "units": 1}),
        ]:
            response = await client.request(method, path + suffix, json=body, headers=headers)
            assert response.status_code == 404
        client.cookies.set("eve_session", token)
        assert (
            await client.delete(path + "/entries/" + entry_id, headers=headers)
        ).status_code == 200
        assert (await client.delete(path, headers=headers)).status_code == 204
        assert (await client.get(path)).status_code == 404
    await svc.repository.delete(first.id, uuid4())
    await container.close()


async def test_invention_decryptor_override_and_best_batch_budget() -> None:
    svc = service()
    row = await svc.create(uuid4(), ProductionCreate(type_id=10))
    market = AsyncMock(spec=ManufacturingRepository)
    market.quotes.return_value = {
        34: price(34, sell_price="100"),
        34201: price(34201, sell_price="1"),
    }
    invention = AsyncMock(spec=InventionRepository)
    now = datetime.now(UTC)
    invention.plan.return_value = PlanState(
        key=settings().plan_key,
        synced_at=now,
        expires_at=now + timedelta(days=1),
        plans=[
            plan(units_per_run=5000),
            plan(
                units_per_run=5000,
                decryptor_id=34201,
                decryptor_name="Accelerant",
                probability="0.6",
                runs_per_copy=20,
                materials=[{"type_id": 34, "quantity": 2}, {"type_id": 34201, "quantity": 1}],
            ),
            plan(
                units_per_run=5000,
                decryptor_id=34202,
                decryptor_name="Symmetry",
                probability="0.7",
                runs_per_copy=30,
                materials=[{"type_id": 34, "quantity": 2}, {"type_id": 34202, "quantity": 1}],
            ),
        ],
    )
    estimator = ProductionEstimateService(svc, market, ShoppingService(invention, market))
    data = EstimateInput(kind="invention", units=50001)
    best = await estimator.estimate(row.user_id, row.id, data)
    assert best.amount == 603
    assert best.selected_decryptor_id == 34201
    assert not best.complete_comparison
    assert len(best.decryptor_options) == 3
    assert [option.decryptor_id for option in best.decryptor_options if option.is_best] == [34201]
    assert best.decryptor_options[-1].estimated_cost is None
    manual = await estimator.estimate(
        row.user_id, row.id, data.model_copy(update={"decryptor_id": None})
    )
    assert manual.amount == 1000
    assert manual.selected_decryptor_id is None
    assert "5 expected attempts" in manual.description
    assert "10 runs / T2 BPC" in manual.description
    small = await estimator.estimate(row.user_id, row.id, data.model_copy(update={"units": 1}))
    assert small.selected_decryptor_id is None
    assert small.amount == 600
    forced = await estimator.estimate(
        row.user_id, row.id, data.model_copy(update={"units": 1, "decryptor_id": 34201})
    )
    assert forced.amount == 603
    for chosen, status in [(1, 422), (34202, 409)]:
        with pytest.raises(ProductionError) as error:
            await estimator.estimate(
                row.user_id, row.id, data.model_copy(update={"decryptor_id": chosen})
            )
        assert (
            error.value.kind
            == {404: ErrorKind.NOT_FOUND, 422: ErrorKind.INVALID_INPUT, 409: ErrorKind.CONFLICT}[
                status
            ]
        )
    assert (await svc.get(row.user_id, row.id)).entries == []


@pytest.mark.parametrize("decryptor", [0, -1, "unknown"])
def test_invalid_decryptor_is_rejected(decryptor: object) -> None:
    with pytest.raises(ValidationError):
        EstimateInput.model_validate({"kind": "invention", "units": 1, "decryptor_id": decryptor})


async def test_purchase_lists_round_runs_exclude_bpcs_and_keep_entries_unchanged() -> None:
    svc = service()
    row = await svc.create(uuid4(), ProductionCreate(type_id=10, units=50001))
    market = AsyncMock(spec=ManufacturingRepository)
    market.recipes.return_value = {10: recipe_state(recipe=recipe(units=5000))}
    market.quotes.return_value = {34: price(34, sell_price="100")}
    invention = AsyncMock(spec=InventionRepository)
    now = datetime.now(UTC)
    invention.plan.return_value = PlanState(
        key=settings().plan_key,
        plans=[plan(units_per_run=5000)],
        synced_at=now,
        expires_at=now + timedelta(days=1),
    )
    estimator = ProductionEstimateService(svc, market, ShoppingService(invention, market))
    materials = await estimator.purchase_list(
        row.user_id, row.id, PurchaseListInput(kind="materials", units=5001)
    )
    assert [(m.type_id, m.quantity) for m in materials.materials] == [(34, 20)]
    copied = await estimator.purchase_list(
        row.user_id, row.id, PurchaseListInput(kind="invention", units=50001)
    )
    assert [(m.type_id, m.quantity) for m in copied.materials] == [(34, 10)]
    assert "T1 BPCs excluded" in copied.description
    updated = await svc.update(
        row.user_id, row.id, ProductionDetails(units=50001, actual_units=45000)
    )
    assert updated.units == 50001
    assert updated.actual_units == 45000
    assert updated.entries == []
    with pytest.raises(ProductionError):
        await estimator.purchase_list(uuid4(), row.id, PurchaseListInput(kind="materials", units=1))
    market.recipes.return_value = {}
    with pytest.raises(ProductionError):
        await estimator.purchase_list(
            row.user_id, row.id, PurchaseListInput(kind="materials", units=1)
        )


async def test_actual_bpc_runs_drive_materials_and_installation_instead_of_planned_units() -> None:
    svc = service()
    row = await svc.create(uuid4(), ProductionCreate(type_id=10, units=999999, actual_runs=3))
    market = AsyncMock(spec=ManufacturingRepository)
    market.recipes.return_value = {10: recipe_state(recipe=recipe(units=5000))}
    market.quotes.return_value = {34: price(34, sell_price="3")}
    estimator = ProductionEstimateService(svc, market, AsyncMock(spec=ShoppingService))
    result = await estimator.purchase_list(
        row.user_id, row.id, PurchaseListInput(kind="materials", manufacturing_runs=3)
    )
    assert result.materials[0].quantity == 30
    assert "15,000 units" in result.description
    cost = await estimator.estimate(
        row.user_id, row.id, EstimateInput(kind="manufacturing", manufacturing_runs=3)
    )
    assert cost.amount == 12
    materials = await estimator.estimate(
        row.user_id, row.id, EstimateInput(kind="materials", manufacturing_runs=3)
    )
    assert materials.amount == 90
    assert (await svc.get(row.user_id, row.id)).units == 999999


@pytest.mark.parametrize(
    "values",
    [
        {"kind": "materials"},
        {"kind": "materials", "units": 100, "manufacturing_runs": 3},
        {"kind": "invention", "manufacturing_runs": 3},
        {"kind": "invention", "units": 100, "manufacturing_runs": 3},
    ],
)
def test_batch_quantity_cannot_mix_runs_and_finished_units(values: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        EstimateInput.model_validate(values)
