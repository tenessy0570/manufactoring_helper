from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core.orm import Base
from app.core.repository import UnitOfWork
from app.domains.accounts.tables import UserTable
from app.domains.exclusions.models import ExcludedItem, ExclusionList
from app.domains.exclusions.repository import ExclusionRepository, SQLExclusionRepository
from app.domains.exclusions.service import ExclusionService


async def test_exclusion_service_commits_deduplicates_and_rolls_back() -> None:
    repo = AsyncMock(spec=ExclusionRepository)
    unit_of_work = AsyncMock(spec=UnitOfWork)
    service = ExclusionService(repo, unit_of_work)
    user = uuid4()
    data = ExclusionList(items=[ExcludedItem(type_id=42, name="Item")] * 2)
    result = await service.save(user, data)
    assert len(result.items) == 1
    unit_of_work.commit.assert_awaited_once()
    await service.get(user)
    repo.get.assert_awaited_once_with(user)
    repo.save.side_effect = ValueError("failed")
    with pytest.raises(ValueError, match="failed"):
        await service.save(user, data)
    unit_of_work.rollback.assert_awaited_once()


async def test_exclusion_repository_isolates_users_and_restores() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with AsyncSession(engine) as session:
        repository = SQLExclusionRepository(session)
        one, two = uuid4(), uuid4()
        for uid in (one, two):
            session.add(
                UserTable(
                    id=uid,
                    username=str(uid)[:20],
                    password_hash="test",
                    is_superuser=False,
                    is_active=True,
                    created_at=datetime.now(UTC),
                )
            )
        await session.flush()
        assert not (await repository.get(one)).items
        data = ExclusionList(items=[ExcludedItem(type_id=42, name="Item")])
        await repository.save(one, data)
        await session.commit()
        assert (await repository.get(one)) == data
        assert not (await repository.get(two)).items
        await repository.save(one, ExclusionList())
        assert not (await repository.get(one)).items
    await engine.dispose()


async def test_exclusion_api_uses_authenticated_user() -> None:
    from types import SimpleNamespace

    import httpx
    from dishka import Provider, Scope, make_async_container
    from fastapi import Request
    from starlette.middleware.base import RequestResponseEndpoint
    from starlette.responses import Response

    from app.main import create_app
    from tests.helpers import make_settings

    service = AsyncMock(spec=ExclusionService)
    service.get.return_value = ExclusionList()
    service.save.return_value = ExclusionList()
    provider = Provider(scope=Scope.REQUEST)
    provider.provide(lambda: service, provides=ExclusionService)
    container = make_async_container(provider)
    app = create_app(container, make_settings(), require_login=False)
    user_id = uuid4()

    @app.middleware("http")
    async def get_session_user(request: Request, call_next: RequestResponseEndpoint) -> Response:
        request.state.user = SimpleNamespace(id=user_id)
        return await call_next(request)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://test"
    ) as client:
        assert (await client.get("/api/v1/opportunity-exclusions")).status_code == 200
        service.get.assert_awaited_once_with(user_id)
        assert (
            await client.put(
                "/api/v1/opportunity-exclusions", json={"items": [], "user_id": str(uuid4())}
            )
        ).status_code == 200
        assert service.save.await_args.args[0] == user_id
    await container.close()
