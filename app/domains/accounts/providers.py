from dishka import Provider, Scope, provide
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.repository import UnitOfWork
from app.domains.accounts.limiter import LoginLimiter, RedisLoginLimiter
from app.domains.accounts.repository import AccountRepository, SQLAccountRepository
from app.domains.accounts.service import AccountService


class AccountProvider(Provider):
    @provide(scope=Scope.REQUEST)
    def provide_repository(self, session: AsyncSession) -> AccountRepository:
        return SQLAccountRepository(session)

    @provide(scope=Scope.APP)
    def provide_login_limiter(self, redis: Redis) -> LoginLimiter:
        return RedisLoginLimiter(redis)

    @provide(scope=Scope.REQUEST)
    def provide_service(
        self,
        repository: AccountRepository,
        unit_of_work: UnitOfWork,
        limiter: LoginLimiter,
        settings: Settings,
    ) -> AccountService:
        return AccountService(repository, unit_of_work, limiter, settings.session_ttl_seconds)
