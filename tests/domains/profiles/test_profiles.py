from collections.abc import AsyncIterator
from decimal import Decimal
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import httpx
import pytest
from dishka import Provider, Scope, make_async_container
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core.orm import Base
from app.core.repository import SQLAlchemyUnitOfWork, UnitOfWork
from app.domains.manufacturing.models import ManufacturingQuery, OpportunityPage
from app.domains.manufacturing.service import ManufacturingService
from app.domains.profiles.models import Profile, ProfileCreate, ProfileSettings, ProfileUpdate
from app.domains.profiles.repository import ProfileRepository, SQLProfileRepository
from app.domains.profiles.service import (
    LastProfileError,
    ProfileCalculationService,
    ProfileNotFoundError,
    ProfileService,
)
from app.main import create_app
from tests.domains.catalog.test_catalog import NOW
from tests.helpers import make_settings

INITIAL_ID = UUID("00000000-0000-0000-0000-000000000001")


def initial() -> Profile:
    return Profile(
        id=INITIAL_ID, name="Default", settings=ProfileSettings(), created_at=NOW, updated_at=NOW
    )


class FakeRepository(ProfileRepository):
    def __init__(self) -> None:
        self.items = {INITIAL_ID: initial()}
        self.default = INITIAL_ID
        self.lock_count = 0

    async def find(self) -> list[Profile]:
        return [
            profile.model_copy(deep=True)
            for profile in sorted(
                self.items.values(), key=lambda profile: (profile.created_at, profile.id)
            )
        ]

    async def get(self, profile_id: UUID) -> Profile | None:
        value = self.items.get(profile_id)
        return None if value is None else value.model_copy(deep=True)

    async def default_id(self, lock: bool = False) -> UUID:
        self.lock_count += lock
        return self.default

    async def save(self, profile: Profile) -> None:
        self.items[profile.id] = profile.model_copy(deep=True)

    async def set_default(self, profile_id: UUID) -> None:
        self.default = profile_id

    async def delete(self, profile_id: UUID) -> None:
        del self.items[profile_id]


async def test_create_copy_update_default_and_delete() -> None:
    repository = FakeRepository()
    uow = AsyncMock(spec=UnitOfWork)
    service = ProfileService(repository, uow, lambda: NOW)
    original = await service.create(
        ProfileCreate(
            name="  Amarr buy  ",
            settings=ProfileSettings(
                hub_id="amarr",
                material_order_type="buy",
                product_order_type="buy",
                sales_tax=Decimal("1.5"),
                broker_fee=Decimal("2.1"),
                include_invention_cost=True,
                min_daily_isk_volume=Decimal("500000000"),
                type_ids=[10, 20],
            ),
        )
    )
    assert original.name == "Amarr buy"
    assert not original.is_default
    copied = await service.copy(original.id, "Copy")
    assert copied.id != original.id
    assert copied.settings == original.settings
    renamed = await service.update(copied.id, ProfileUpdate(name="  Renamed  "))
    assert renamed.name == "Renamed"
    assert renamed.settings == original.settings
    changed = await service.update(copied.id, ProfileUpdate(settings=ProfileSettings(hub_id="hek")))
    assert changed.settings.hub_id == "hek"
    assert (await service.get(original.id)).settings.hub_id == "amarr"
    assert (await service.set_default(copied.id)).is_default
    page = await service.find()
    assert sum(profile.is_default for profile in page.items) == 1
    assert page.default_profile_id == copied.id
    await service.delete(copied.id)
    assert (await service.get()).id == INITIAL_ID
    await service.delete(original.id)
    with pytest.raises(LastProfileError):
        await service.delete(INITIAL_ID)
    with pytest.raises(ProfileNotFoundError):
        await service.get(uuid4())
    assert repository.lock_count >= 7
    assert await service.find() == await service.find()


@pytest.mark.parametrize("operation", ["create", "update", "set_default", "delete"])
async def test_commit_failure_rolls_back(operation: str) -> None:
    repository = FakeRepository()
    uow = AsyncMock(spec=UnitOfWork)
    uow.commit.side_effect = RuntimeError("write failed")
    service = ProfileService(repository, uow)
    repository.items[UUID(int=2)] = initial().model_copy(update={"id": UUID(int=2)})

    async def execute() -> None:
        if operation == "create":
            await service.create(ProfileCreate(name="new"))
        elif operation == "update":
            await service.update(INITIAL_ID, ProfileUpdate(name="new"))
        elif operation == "set_default":
            await service.set_default(INITIAL_ID)
        else:
            await service.delete(INITIAL_ID)

    with pytest.raises(RuntimeError, match="write failed"):
        await execute()
    uow.rollback.assert_awaited_once()


def test_validates_settings_and_keeps_latest_defaults() -> None:
    settings = ProfileSettings()
    assert settings.material_order_type == settings.product_order_type == "sell"
    assert settings.sales_tax == settings.broker_fee == 0
    for invalid in (
        {"me": 10},
        {"te": 20},
        {"offset": 5},
        {"sales_tax": 101},
        {"min_profit": 100, "max_profit": 0},
    ):
        with pytest.raises(ValidationError):
            ProfileSettings.model_validate(invalid)
    for payload in ({"name": "   "}, {"name": None}, {"settings": None}):
        with pytest.raises(ValidationError):
            ProfileUpdate.model_validate(payload)
    with pytest.raises(ValidationError):
        ProfileCreate(name="   ")


@pytest.fixture
async def session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with AsyncSession(engine, expire_on_commit=False) as session:
        repository = SQLProfileRepository(session)
        await repository.save(initial())
        await repository.set_default(INITIAL_ID)
        await session.commit()
        yield session
    await engine.dispose()


async def test_sql_persists_settings_and_default_across_sessions(session: AsyncSession) -> None:
    repository = SQLProfileRepository(session)
    service = ProfileService(repository, SQLAlchemyUnitOfWork(session), lambda: NOW)
    profile = await service.create(
        ProfileCreate(
            name="Saved",
            settings=ProfileSettings(
                sales_tax=Decimal("2.5"),
                material_hub_id="amarr",
                has_history=True,
                fresh_only=True,
                min_product_volume=500,
            ),
        )
    )
    await service.set_default(profile.id)
    async with AsyncSession(session.bind) as other:
        restored = SQLProfileRepository(other)
        assert await restored.default_id(lock=True) == profile.id
        loaded = await restored.get(profile.id)
        assert loaded is not None
        assert loaded.settings == profile.settings
    await repository.save(profile.model_copy(update={"name": "Temporary"}))
    await session.rollback()
    assert (await service.get(profile.id)).name == "Saved"
    await service.delete(profile.id)
    assert await repository.default_id() == INITIAL_ID
    assert await repository.get(profile.id) is None
    await repository.delete(uuid4())


async def test_calculation_uses_saved_settings_with_ephemeral_pagination() -> None:
    repository = FakeRepository()
    repository.items[INITIAL_ID].settings = ProfileSettings(
        hub_id="hek", limit=17, material_order_type="buy", include_invention_cost=True
    )
    service = ProfileService(repository, AsyncMock(spec=UnitOfWork))
    manufacturing = AsyncMock(spec=ManufacturingService)
    calculation = ProfileCalculationService(service, manufacturing)
    await calculation.opportunities(None, None, 5)
    assert manufacturing.opportunities.await_args is not None
    query = manufacturing.opportunities.await_args.args[0]
    assert isinstance(query, ManufacturingQuery)
    assert query.hub_id == "hek"
    assert query.limit == 17
    assert query.offset == 5
    assert query.include_invention_cost
    await calculation.opportunities(INITIAL_ID, 25, 0)
    assert manufacturing.opportunities.await_args.args[0].limit == 25
    assert repository.items[INITIAL_ID].settings.offset == 0
    assert repository.items[INITIAL_ID].settings.limit == 17


async def test_api_profile_lifecycle_and_errors() -> None:
    service = ProfileService(FakeRepository(), AsyncMock(spec=UnitOfWork), lambda: NOW)
    manufacturing = AsyncMock(spec=ManufacturingService)
    manufacturing.opportunities.return_value = OpportunityPage(
        hub_id="jita",
        material_hub_id="jita",
        material_order_type="sell",
        product_order_type="sell",
        sales_tax=Decimal(0),
        broker_fee=Decimal(0),
        items=[],
        total=0,
        missing_recipes=0,
        non_manufacturable=0,
        missing_prices=0,
        limit=100,
        offset=0,
    )
    calculation = ProfileCalculationService(service, manufacturing)
    provider = Provider(scope=Scope.REQUEST)
    provider.provide(lambda: service, provides=ProfileService)
    provider.provide(lambda: calculation, provides=ProfileCalculationService)
    container = make_async_container(provider)
    app = create_app(container=container, settings=make_settings())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://test"
    ) as client:
        assert (await client.get("/api/v1/profiles")).status_code == 200
        assert (await client.get("/api/v1/profiles/default")).json()["is_default"]
        assert (await client.delete(f"/api/v1/profiles/{INITIAL_ID}")).status_code == 409
        created = await client.post("/api/v1/profiles", json={"name": "test"})
        assert created.status_code == 201
        profile_id = created.json()["id"]
        assert (await client.get(f"/api/v1/profiles/{profile_id}")).status_code == 200
        assert (
            await client.patch(f"/api/v1/profiles/{profile_id}", json={"name": "changed"})
        ).status_code == 200
        assert (
            await client.post(f"/api/v1/profiles/{profile_id}/copy", json={"name": "copy"})
        ).status_code == 201
        assert (await client.put(f"/api/v1/profiles/{profile_id}/default")).json()["is_default"]
        assert (
            await client.get(f"/api/v1/profiles/{profile_id}/opportunities?limit=10")
        ).status_code == 200
        assert (await client.get("/api/v1/profiles/default/opportunities")).status_code == 200
        assert (await client.delete(f"/api/v1/profiles/{profile_id}")).status_code == 204
        missing = str(uuid4())
        for method, path, payload in (
            ("GET", missing, None),
            ("PATCH", missing, {"name": "x"}),
            ("POST", f"{missing}/copy", {"name": "x"}),
            ("PUT", f"{missing}/default", None),
            ("DELETE", missing, None),
            ("GET", f"{missing}/opportunities", None),
        ):
            assert (
                await client.request(method, f"/api/v1/profiles/{path}", json=payload)
            ).status_code == 404
        assert (
            await client.post("/api/v1/profiles", json={"name": "x", "settings": {"me": 10}})
        ).status_code == 422
    await container.close()
