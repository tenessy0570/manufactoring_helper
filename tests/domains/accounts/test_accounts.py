from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import httpx
import pytest
from dishka import Provider, Scope, make_async_container
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core.application_errors import ErrorKind
from app.core.orm import Base
from app.core.repository import SQLAlchemyUnitOfWork
from app.domains.accounts.errors import AccountError
from app.domains.accounts.limiter import LoginLimiter, RedisLoginLimiter
from app.domains.accounts.models import Credentials, PasswordChange, User, UserCreate, UserUpdate
from app.domains.accounts.passwords import hash_password, verify_password
from app.domains.accounts.repository import SQLAccountRepository
from app.domains.accounts.service import COOKIE_NAME, AccountService, hash_session_token
from app.main import create_app
from tests.helpers import make_settings

PASSWORD = "test-password-for-tests"
HEADERS = {"X-Requested-With": "XMLHttpRequest"}


class Limiter(LoginLimiter):
    allowed = True

    async def allow(self, username: str, address: str) -> bool:
        return self.allowed


@pytest.fixture
async def service() -> AsyncIterator[AccountService]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with AsyncSession(engine, expire_on_commit=False) as session:
        yield AccountService(
            SQLAccountRepository(session), SQLAlchemyUnitOfWork(session), Limiter()
        )
    await engine.dispose()


async def make_user(service: AccountService, username: str = "admin", admin: bool = True) -> User:
    return await service.create(
        UserCreate.model_validate(
            {"username": username, "password": PASSWORD, "is_superuser": admin}
        )
    )


def credentials(username: str = "admin", password: str = PASSWORD) -> Credentials:
    return Credentials.model_validate({"username": username, "password": password})


def test_password_hashes_are_salted_and_verify() -> None:
    encoded = hash_password(PASSWORD)
    assert encoded != hash_password(PASSWORD)
    assert PASSWORD not in encoded
    assert verify_password(PASSWORD, encoded)
    assert not verify_password("wrong", encoded)
    assert not verify_password(PASSWORD, "bad")
    assert not verify_password(PASSWORD, "other$00$00")


async def test_login_rotation_revocation_password_and_disabled_user(
    service: AccountService,
) -> None:
    actor = await make_user(service)
    for username, password in (("missing", PASSWORD), ("admin", "wrong")):
        with pytest.raises(AccountError) as error:
            await service.login(credentials(username, password), "test")
        assert error.value.kind == ErrorKind.UNAUTHENTICATED
    identity, token = await service.login(credentials("ADMIN"), "test")
    assert identity.id == actor.id
    assert await service.get_session_user(token) == identity
    _, rotated = await service.login(credentials(), "test", previous=token)
    assert await service.get_session_user(token) is None
    assert await service.get_session_user(rotated) is not None
    await service.logout(rotated)
    assert await service.get_session_user(rotated) is None
    with pytest.raises(AccountError):
        await service.change_password(
            actor,
            PasswordChange.model_validate(
                {"current_password": "wrong", "new_password": "another-password"}
            ),
        )
    await service.change_password(
        actor,
        PasswordChange.model_validate(
            {"current_password": PASSWORD, "new_password": "another-password"}
        ),
    )
    with pytest.raises(AccountError):
        await service.login(credentials(), "test")
    _, token = await service.login(credentials(password="another-password"), "test")
    await service.change_password(
        actor,
        PasswordChange.model_validate(
            {"current_password": "another-password", "new_password": PASSWORD}
        ),
    )
    assert await service.get_session_user(token) is None
    ordinary = await make_user(service, "ordinary", False)
    _, ordinary_token = await service.login(credentials("ordinary"), "test")
    await service.update(ordinary.id, UserUpdate(is_active=False), actor)
    assert await service.get_session_user(ordinary_token) is None
    with pytest.raises(AccountError):
        await service.login(credentials("ordinary"), "test")
    await service.update(ordinary.id, UserUpdate(is_active=True), actor)
    assert (await service.login(credentials("ordinary"), "test"))[0].is_active
    with pytest.raises(AccountError):
        await service.update(actor.id, UserUpdate(is_active=False), actor)
    with pytest.raises(AccountError):
        await service.update(uuid4(), UserUpdate(is_active=False), actor)
    with pytest.raises(AccountError) as error:
        await make_user(service, "ADMIN")
    assert error.value.kind == ErrorKind.CONFLICT
    assert len(await service.find()) == 2


async def test_expired_session_and_rate_limit(service: AccountService) -> None:
    actor = await make_user(service)
    await service.repository.create_session(
        hash_session_token("expired"), actor.id, datetime.now(UTC) - timedelta(seconds=1)
    )
    await service.unit_of_work.commit()
    assert await service.get_session_user("expired") is None
    assert isinstance(service.limiter, Limiter)
    service.limiter.allowed = False
    with pytest.raises(AccountError) as error:
        await service.login(credentials(), "test")
    assert error.value.kind == ErrorKind.RATE_LIMITED


async def test_whole_site_gate_roles_csrf_and_cookie(service: AccountService) -> None:
    await make_user(service)
    await make_user(service, "ordinary", False)
    provider = Provider(scope=Scope.REQUEST)
    provider.provide(lambda: service, provides=AccountService)
    container = make_async_container(provider)
    app = create_app(container, make_settings())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://test"
    ) as client:
        for path in (
            "/",
            "/blueprint-calculator",
            "/interhub-trading",
            "/invention-shopping",
            "/account",
            "/admin",
            "/docs",
            "/openapi.json",
        ):
            assert (await client.get(path)).status_code == 303
        for path in (
            "/api/v1/catalog/items",
            "/api/v1/manufacturing/calculator/10",
            "/api/v1/trading/opportunities",
            "/health/data-progress",
            "/api/v1/accounts/users",
        ):
            assert (await client.get(path)).status_code == 401
        assert (await client.get("/login")).status_code == 200
        assert (await client.get("/health/live")).status_code == 200
        assert (await client.get("/static/account.js")).status_code == 200
        assert (
            await client.post(
                "/api/v1/accounts/login", json={"username": "admin", "password": PASSWORD}
            )
        ).status_code == 403
        assert (
            await client.post(
                "/api/v1/accounts/login",
                json={"username": "admin", "password": PASSWORD},
                headers={**HEADERS, "Origin": "http://evil.example"},
            )
        ).status_code == 403
        login = await client.post(
            "/api/v1/accounts/login",
            json={"username": "admin", "password": PASSWORD},
            headers=HEADERS,
        )
        assert login.status_code == 200
        assert "httponly" in login.headers["set-cookie"].lower()
        assert "samesite=lax" in login.headers["set-cookie"].lower()
        assert "password_hash" not in login.text
        assert (await client.get("/admin")).status_code == 200
        assert (await client.get("/account")).status_code == 200
        users = await client.get("/api/v1/accounts/users")
        assert users.status_code == 200
        assert "password_hash" not in users.text
        assert (await client.get("/api/v1/accounts/me")).json()["username"] == "admin"
        created = await client.post(
            "/api/v1/accounts/users",
            json={"username": "third", "password": PASSWORD},
            headers=HEADERS,
        )
        assert created.status_code == 201
        target = created.json()["id"]
        assert (
            await client.patch(
                "/api/v1/accounts/users/" + target, json={"is_active": False}, headers=HEADERS
            )
        ).status_code == 200
        assert (await client.post("/api/v1/accounts/logout", headers=HEADERS)).status_code == 204
        assert COOKIE_NAME not in client.cookies
        await client.post(
            "/api/v1/accounts/login",
            json={"username": "ordinary", "password": PASSWORD},
            headers=HEADERS,
        )
        assert (await client.get("/admin")).status_code == 403
        assert (await client.get("/api/v1/accounts/users")).status_code == 403
        assert (
            await client.post(
                "/api/v1/accounts/users",
                json={"username": "bad", "password": PASSWORD},
                headers=HEADERS,
            )
        ).status_code == 403
        changed = await client.post(
            "/api/v1/accounts/password",
            json={"current_password": PASSWORD, "new_password": "updated-test-password"},
            headers=HEADERS,
        )
        assert changed.status_code == 204
        assert (await client.get("/api/v1/accounts/me")).status_code == 401
    await container.close()


async def test_limiter_limits_account_and_address() -> None:
    counts: dict[str, int] = {}

    async def increment(script: str, number: int, key: str) -> int:
        counts[key] = counts.get(key, 0) + 1
        return counts[key]

    redis = AsyncMock(spec=Redis)
    redis.eval = AsyncMock(side_effect=increment)
    limiter = RedisLoginLimiter(redis)
    for _ in range(10):
        assert await limiter.allow("admin", "same")
    assert not await limiter.allow("admin", "same")
    for i in range(50):
        await limiter.allow(str(i), "other")
    assert not await limiter.allow("new", "other")


async def test_hash_only_sessions_on_https_and_rollback(
    service: AccountService, monkeypatch: pytest.MonkeyPatch
) -> None:
    await make_user(service)
    provider = Provider(scope=Scope.REQUEST)
    provider.provide(lambda: service, provides=AccountService)
    container = make_async_container(provider)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(create_app(container, make_settings(), require_login=True)),
        base_url="https://test",
    ) as client:
        result = await client.post(
            "/api/v1/accounts/login",
            json={"username": "admin", "password": PASSWORD},
            headers=HEADERS,
        )
        assert "secure" in result.headers["set-cookie"].lower()
        await client.post("/api/v1/accounts/logout", headers=HEADERS)
    await container.close()
    original = service.repository.create_session

    async def fail_session(token: str, user_id: UUID, expires: datetime) -> None:
        raise RuntimeError("storage failure")

    monkeypatch.setattr(service.repository, "create_session", fail_session)
    with pytest.raises(RuntimeError, match="storage failure"):
        await service.login(credentials(), "test")
    monkeypatch.setattr(service.repository, "create_session", original)
    assert (await service.login(credentials(), "test"))[0].username == "admin"
