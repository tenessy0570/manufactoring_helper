from datetime import datetime
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

from app.core.repository import UnitOfWork
from app.domains.accounts.models import Credentials, StoredUser, UserCreate
from app.domains.accounts.repository import AccountRepository
from app.domains.accounts.service import AccountService
from tests.domains.accounts.test_accounts import PASSWORD, Limiter


class MemoryAccounts(AccountRepository):
    def __init__(self) -> None:
        self.users: dict[UUID, StoredUser] = {}
        self.sessions: dict[str, tuple[UUID, datetime]] = {}

    async def lock_admins(self) -> None:
        pass

    async def find(self) -> list[StoredUser]:
        return list(self.users.values())

    async def get_by_username(self, username: str) -> StoredUser | None:
        return next((user for user in self.users.values() if user.username == username), None)

    async def get(self, user_id: UUID) -> StoredUser | None:
        return self.users.get(user_id)

    async def save(self, user: StoredUser) -> None:
        self.users[user.id] = user.model_copy(deep=True)

    async def get_session_user(self, token_hash: str, now: datetime) -> StoredUser | None:
        session = self.sessions.get(token_hash)
        user = self.users.get(session[0]) if session else None
        return user if session and session[1] > now and user and user.is_active else None

    async def create_session(self, token_hash: str, user_id: UUID, expires: datetime) -> None:
        self.sessions[token_hash] = (user_id, expires)

    async def revoke(self, token_hash: str) -> None:
        self.sessions.pop(token_hash, None)

    async def revoke_user(self, user_id: UUID) -> None:
        self.sessions = {key: value for key, value in self.sessions.items() if value[0] != user_id}


async def test_service_uses_opaque_revocable_sessions_and_uow() -> None:
    repository = MemoryAccounts()
    unit_of_work = AsyncMock(spec=UnitOfWork)
    service = AccountService(repository, unit_of_work, Limiter())
    user = await service.create(
        UserCreate.model_validate({"username": "example", "password": PASSWORD})
    )
    _, token = await service.login(
        Credentials.model_validate({"username": "example", "password": PASSWORD}), "test"
    )
    assert token not in repository.sessions
    assert "password_hash" not in user.model_dump()
    assert await service.get_session_user(token) == user
    assert unit_of_work.commit.await_count == 2
    await service.logout(token)
    assert await service.get_session_user(token) is None
    unit_of_work.commit.side_effect = RuntimeError("commit failed")
    with pytest.raises(RuntimeError, match="commit failed"):
        await service.create(
            UserCreate.model_validate({"username": "another", "password": PASSWORD})
        )
    unit_of_work.rollback.assert_awaited_once()
