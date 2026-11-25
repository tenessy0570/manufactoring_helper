import asyncio
import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from app.core.application_errors import ErrorKind
from app.core.repository import UnitOfWork
from app.domains.accounts.errors import AccountError
from app.domains.accounts.limiter import LoginLimiter
from app.domains.accounts.models import (
    Credentials,
    PasswordChange,
    StoredUser,
    User,
    UserCreate,
    UserUpdate,
)
from app.domains.accounts.passwords import hash_password, verify_password
from app.domains.accounts.repository import AccountRepository, DuplicateUsernameError

COOKIE_NAME = "eve_session"


def hash_session_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class AccountService:
    def __init__(
        self,
        repository: AccountRepository,
        unit_of_work: UnitOfWork,
        limiter: LoginLimiter,
        session_seconds: int = 1209600,
    ) -> None:
        self.repository, self.unit_of_work, self.limiter = repository, unit_of_work, limiter
        self.session_seconds = session_seconds

    async def get_session_user(self, token: str) -> User | None:
        user = await self.repository.get_session_user(hash_session_token(token), datetime.now(UTC))
        return None if user is None else User.model_validate(user.model_dump())

    async def login(self, data: Credentials, address: str, previous: str = "") -> tuple[User, str]:
        username = data.username.lower()
        if not await self.limiter.allow(username, address):
            raise AccountError(
                ErrorKind.RATE_LIMITED, "Too many login attempts. Try again in 15 minutes."
            )
        user = await self.repository.get_by_username(username)
        encoded = user.password_hash if user else "scrypt$" + "00" * 16 + "$" + "00" * 64
        valid = await asyncio.to_thread(verify_password, data.password.get_secret_value(), encoded)
        if user is None or not valid or not user.is_active:
            raise AccountError(ErrorKind.UNAUTHENTICATED, "Invalid username or password")
        token = secrets.token_urlsafe(32)
        try:
            if previous:
                await self.repository.revoke(hash_session_token(previous))
            await self.repository.create_session(
                hash_session_token(token),
                user.id,
                datetime.now(UTC) + timedelta(seconds=self.session_seconds),
            )
            await self.unit_of_work.commit()
        except BaseException:
            await self.unit_of_work.rollback()
            raise
        return User.model_validate(user.model_dump()), token

    async def logout(self, token: str) -> None:
        await self.repository.revoke(hash_session_token(token))
        await self.unit_of_work.commit()

    async def create(self, data: UserCreate) -> User:
        user = StoredUser(
            id=uuid4(),
            username=data.username.lower(),
            password_hash=await asyncio.to_thread(hash_password, data.password.get_secret_value()),
            is_superuser=data.is_superuser,
            created_at=datetime.now(UTC),
        )
        try:
            await self.repository.save(user)
            await self.unit_of_work.commit()
        except DuplicateUsernameError as error:
            await self.unit_of_work.rollback()
            raise AccountError(ErrorKind.CONFLICT, "Username already exists") from error
        except BaseException:
            await self.unit_of_work.rollback()
            raise
        return User.model_validate(user.model_dump())

    async def find(self) -> list[User]:
        return [User.model_validate(user.model_dump()) for user in await self.repository.find()]

    async def update(self, user_id: UUID, data: UserUpdate, actor: User) -> User:
        await self.repository.lock_admins()
        current_actor = await self.repository.get(actor.id)
        if current_actor is None or not current_actor.is_active:
            raise AccountError(ErrorKind.FORBIDDEN, "Account is no longer active")
        if not current_actor.is_superuser and (user_id != actor.id or data.is_active is not None):
            raise AccountError(ErrorKind.FORBIDDEN, "Superuser access required")
        if user_id == actor.id and data.is_active is False:
            raise AccountError(ErrorKind.CONFLICT, "You cannot disable your own account")
        user = await self.repository.get(user_id)
        if user is None:
            raise AccountError(ErrorKind.NOT_FOUND, "User not found")
        if data.is_active is not None:
            user.is_active = data.is_active
        if data.password is not None:
            user.password_hash = await asyncio.to_thread(
                hash_password, data.password.get_secret_value()
            )
        try:
            await self.repository.save(user)
            if data.password is not None or data.is_active is False:
                await self.repository.revoke_user(user.id)
            await self.unit_of_work.commit()
        except BaseException:
            await self.unit_of_work.rollback()
            raise
        return User.model_validate(user.model_dump())

    async def change_password(self, actor: User, data: PasswordChange) -> None:
        user = await self.repository.get(actor.id)
        if user is None or not await asyncio.to_thread(
            verify_password, data.current_password.get_secret_value(), user.password_hash
        ):
            raise AccountError(ErrorKind.INVALID_OPERATION, "Current password is incorrect")
        await self.update(actor.id, UserUpdate(password=data.new_password), actor)
