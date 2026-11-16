from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock

import httpx
import pytest
from dishka import Provider, Scope, make_async_container
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core.orm import Base
from app.core.repository import Page, SQLAlchemyUnitOfWork
from app.domains.catalog.gateway import CatalogGateway
from app.domains.catalog.models import ItemType, ItemTypeClause, MarketGroup
from app.domains.catalog.repository import SQLItemTypeRepository
from app.domains.catalog.selector import MarketTreeSelector
from app.domains.catalog.service import CatalogService, CatalogSyncService
from app.main import create_app
from tests.helpers import make_settings

NOW = datetime(2026, 11, 16, tzinfo=UTC)


def groups() -> list[MarketGroup]:
    return [
        MarketGroup(market_group_id=1, name="Ship Equipment", types=[10]),
        MarketGroup(market_group_id=2, name="Ammunition & Charges"),
        MarketGroup(market_group_id=3, name="Drones", types=[30]),
        MarketGroup(market_group_id=4, name="Rigs", parent_group_id=1, types=[40]),
        MarketGroup(market_group_id=5, name="Capital Rigs", parent_group_id=4, types=[50]),
        MarketGroup(market_group_id=6, name="Shield Rigs", parent_group_id=4, types=[60]),
    ]


def item(type_id: int = 10, **overrides: Any) -> ItemType:
    return ItemType.model_validate(
        {
            "type_id": type_id,
            "name": "Shield Rig",
            "market_group_id": 4,
            "market_group_name": "Rigs",
            "category": "Ship Equipment",
            "group_path": [1, 4],
            "is_rig": True,
            "meta_group_id": 2,
            "synced_at": NOW,
            **overrides,
        }
    )


@pytest.fixture
async def session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with AsyncSession(engine, expire_on_commit=False) as session:
        yield session
    await engine.dispose()


def test_selector_preserves_categories_paths_and_rigs() -> None:
    selected = MarketTreeSelector().select(groups())
    assert [entry.type_id for entry in selected] == [10, 30, 40, 60]
    assert selected[-1].group_path == [1, 4, 6]
    assert selected[-1].is_rig
    assert selected[1].category == "Drones"
    assert not selected[0].is_rig


def test_selector_rejects_incomplete_tree() -> None:
    with pytest.raises(ValueError, match="roots"):
        MarketTreeSelector().select([])
    with pytest.raises(ValueError, match="Incomplete"):
        MarketTreeSelector().select(
            [MarketGroup(market_group_id=1, name="Rigs", parent_group_id=8)]
        )


async def test_upsert_batches_updates_and_deactivation(session: AsyncSession) -> None:
    repository = SQLItemTypeRepository(session)
    assert await repository.latest_synced_at() is None
    await repository.upsert_many([item(number) for number in range(205)])
    await repository.upsert_many([item(10, name="Changed", synced_at=NOW + timedelta(days=1))])
    await repository.upsert_many([])
    assert await repository.count() == 205
    updated = await repository.get(10)
    assert updated is not None
    assert updated.name == "Changed"
    await repository.deactivate_before(NOW + timedelta(days=1))
    assert await repository.count() == 1
    assert await repository.count(ItemTypeClause(is_active=False)) == 204
    assert await repository.latest_synced_at() == NOW + timedelta(days=1)


@pytest.mark.parametrize(
    ("filters", "expected"),
    [
        ({}, [10, 20, 30]),
        ({"search": "shield"}, [10, 30]),
        ({"search": "%"}, [30]),
        ({"type_ids": [30, 10], "exclude_type_ids": [10]}, [30]),
        ({"type_ids": []}, []),
        ({"categories": ["Drones"]}, [20]),
        ({"market_group_ids": [4]}, [10, 30]),
        ({"meta_group_ids": [2]}, [10]),
        ({"is_rig": False}, [20]),
        ({"is_rig": True, "has_meta_group": True}, [10]),
        ({"has_meta_group": False}, [30]),
        ({"is_active": False}, [40]),
        ({"is_active": None}, [10, 20, 30, 40]),
    ],
)
async def test_filters(session: AsyncSession, filters: dict[str, Any], expected: list[int]) -> None:
    repository = SQLItemTypeRepository(session)
    await repository.upsert_many(
        [
            item(10),
            item(
                20,
                name="Drone",
                category="Drones",
                is_rig=False,
                market_group_id=3,
                meta_group_id=1,
            ),
            item(30, name="Shield 100%", meta_group_id=None),
            item(40, is_active=False),
        ]
    )
    clause = ItemTypeClause.model_validate(filters)
    assert [entry.type_id for entry in await repository.find(clause)] == expected
    assert await repository.count(clause) == len(expected)
    assert len(await repository.find(clause, Page(limit=1))) == min(1, len(expected))


class FakeGateway(CatalogGateway):
    def __init__(self) -> None:
        self.groups = groups()
        self.metadata_calls: list[int] = []
        self.fail_metadata = False
        self.missing_group = False
        self.missing_names = False

    async def list_market_group_ids(self) -> list[int]:
        return [group.market_group_id for group in self.groups]

    async def get_market_group(self, group_id: int) -> MarketGroup | None:
        return (
            None
            if self.missing_group
            else next(group for group in self.groups if group.market_group_id == group_id)
        )

    async def get_meta_group_id(self, type_id: int) -> int | None:
        self.metadata_calls.append(type_id)
        if self.fail_metadata:
            raise ConnectionError("offline")
        return 2

    async def resolve_names(self, type_ids: Sequence[int]) -> dict[int, str]:
        return {} if self.missing_names else {type_id: f"Item {type_id}" for type_id in type_ids}


async def test_sync_reuses_metadata_retries_missing_and_skips_fresh(session: AsyncSession) -> None:
    repository = SQLItemTypeRepository(session)
    gateway = FakeGateway()
    service = CatalogSyncService(
        repository, gateway, SQLAlchemyUnitOfWork(session), MarketTreeSelector(), lambda: NOW
    )
    gateway.fail_metadata = True
    assert (await service.sync()).missing_metadata == 4
    gateway.fail_metadata = False
    assert (await service.sync()).missing_metadata == 0
    assert len(gateway.metadata_calls) == 8
    await service.sync()
    assert len(gateway.metadata_calls) == 8
    assert (await service.sync_if_stale(timedelta(days=1))).skipped
    assert not (await service.sync_if_stale(timedelta(0))).skipped
    assert await repository.count() == 4


@pytest.mark.parametrize("failure", ["missing_group", "missing_names", "empty"])
async def test_incomplete_sync_preserves_data(session: AsyncSession, failure: str) -> None:
    repository = SQLItemTypeRepository(session)
    await repository.upsert_many([item()])
    await session.commit()
    gateway = FakeGateway()
    if failure == "empty":
        for group in gateway.groups:
            group.types = []
    else:
        setattr(gateway, failure, True)
    service = CatalogSyncService(
        repository, gateway, SQLAlchemyUnitOfWork(session), MarketTreeSelector()
    )
    with pytest.raises(ValueError, match=r"disappeared|Missing name|Empty catalog"):
        await service.sync()
    assert await repository.count() == 1


async def test_sync_rolls_back_failed_write(session: AsyncSession) -> None:
    repository = SQLItemTypeRepository(session)
    uow = AsyncMock(spec=SQLAlchemyUnitOfWork)
    uow.commit.side_effect = RuntimeError("commit failed")
    service = CatalogSyncService(repository, FakeGateway(), uow, MarketTreeSelector())
    with pytest.raises(RuntimeError, match="commit failed"):
        await service.sync()
    uow.rollback.assert_awaited_once()


async def test_api_combines_filters_pagination_and_validates(session: AsyncSession) -> None:
    repository = SQLItemTypeRepository(session)
    await repository.upsert_many([item(10), item(20), item(30, meta_group_id=1)])
    provider = Provider(scope=Scope.REQUEST)
    provider.provide(lambda: CatalogService(repository), provides=CatalogService)
    container = make_async_container(provider)
    app = create_app(container=container, settings=make_settings())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://test"
    ) as client:
        response = await client.get(
            "/api/v1/catalog/items",
            params={
                "search": "shield",
                "is_rig": "true",
                "meta_group_ids": 2,
                "limit": 1,
                "offset": 1,
            },
        )
        assert response.status_code == 200, response.text
        assert response.json()["total"] == 2
        assert response.json()["items"][0]["type_id"] == 20
        assert (await client.get("/api/v1/catalog/items?limit=0")).status_code == 422
    await container.close()
