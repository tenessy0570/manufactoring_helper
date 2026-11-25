from abc import ABC, abstractmethod
from datetime import datetime
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.accounts.models import StoredUser
from app.domains.accounts.tables import SessionTable, UserTable


class DuplicateUsernameError(Exception):
    pass


class AccountRepository(ABC):
    @abstractmethod
    async def lock_admins(self) -> None: ...

    @abstractmethod
    async def find(self) -> list[StoredUser]: ...
    @abstractmethod
    async def get_by_username(self, username: str) -> StoredUser | None: ...
    @abstractmethod
    async def get(self, user_id: UUID) -> StoredUser | None: ...
    @abstractmethod
    async def save(self, user: StoredUser) -> None: ...
    @abstractmethod
    async def get_session_user(self, token_hash: str, now: datetime) -> StoredUser | None: ...
    @abstractmethod
    async def create_session(self, token_hash: str, user_id: UUID, expires: datetime) -> None: ...
    @abstractmethod
    async def revoke(self, token_hash: str) -> None: ...
    @abstractmethod
    async def revoke_user(self, user_id: UUID) -> None: ...


class SQLAccountRepository(AccountRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def lock_admins(self) -> None:
        await self._session.scalars(
            select(UserTable)
            .where(UserTable.is_superuser.is_(True))
            .order_by(UserTable.id)
            .with_for_update()
        )

    async def find(self) -> list[StoredUser]:
        rows = await self._session.scalars(select(UserTable).order_by(UserTable.username))
        return [StoredUser.model_validate(row, from_attributes=True) for row in rows]

    async def get_by_username(self, username: str) -> StoredUser | None:
        row = await self._session.scalar(select(UserTable).where(UserTable.username == username))
        return None if row is None else StoredUser.model_validate(row, from_attributes=True)

    async def get(self, user_id: UUID) -> StoredUser | None:
        row = await self._session.get(UserTable, user_id, populate_existing=True)
        return None if row is None else StoredUser.model_validate(row, from_attributes=True)

    async def save(self, user: StoredUser) -> None:
        try:
            await self._session.merge(UserTable(**user.model_dump()))
            await self._session.flush()
        except IntegrityError as error:
            raise DuplicateUsernameError from error

    async def get_session_user(self, token_hash: str, now: datetime) -> StoredUser | None:
        row = await self._session.scalar(
            select(UserTable)
            .join(SessionTable)
            .where(
                SessionTable.token_hash == token_hash,
                SessionTable.expires_at > now,
                UserTable.is_active.is_(True),
            )
        )
        return None if row is None else StoredUser.model_validate(row, from_attributes=True)

    async def create_session(self, token_hash: str, user_id: UUID, expires: datetime) -> None:
        await self._session.execute(
            delete(SessionTable).where(SessionTable.expires_at < datetime.now(expires.tzinfo))
        )
        self._session.add(SessionTable(token_hash=token_hash, user_id=user_id, expires_at=expires))
        await self._session.flush()

    async def revoke(self, token_hash: str) -> None:
        await self._session.execute(
            delete(SessionTable).where(SessionTable.token_hash == token_hash)
        )
        await self._session.flush()

    async def revoke_user(self, user_id: UUID) -> None:
        await self._session.execute(delete(SessionTable).where(SessionTable.user_id == user_id))
        await self._session.flush()
