from collections.abc import AsyncIterator

from dishka import Provider, Scope, from_context, provide
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.cache import Cache, CacheService, MemoryCache, RedisCache, TieredCache
from app.core.config import RefreshPolicy, Settings
from app.core.database import create_engine, create_session_factory
from app.core.repository import SQLAlchemyUnitOfWork, UnitOfWork


class InfrastructureProvider(Provider):
    """Wires settings, database, Redis, cache and the per-request transaction objects."""

    settings = from_context(provides=Settings, scope=Scope.APP)

    @provide(scope=Scope.APP)
    def refresh_policy(self, settings: Settings) -> RefreshPolicy:
        return settings.refresh_policy

    @provide(scope=Scope.APP)
    async def engine(self, settings: Settings) -> AsyncIterator[AsyncEngine]:
        engine = create_engine(settings)
        yield engine
        await engine.dispose()

    @provide(scope=Scope.APP)
    def session_factory(self, engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
        return create_session_factory(engine)

    @provide(scope=Scope.APP)
    async def redis(self, settings: Settings) -> AsyncIterator[Redis]:
        client: Redis = Redis(
            host=settings.redis_host,
            port=settings.redis_port,
            password=settings.redis_password.get_secret_value(),
            decode_responses=True,
        )
        yield client
        await client.aclose()

    @provide(scope=Scope.APP)
    def cache(self, settings: Settings, redis: Redis) -> Cache:
        return TieredCache(
            memory=MemoryCache(max_items=settings.memory_cache_max_items),
            persistent=RedisCache(redis),
            memory_ttl_seconds=settings.memory_cache_ttl_seconds,
        )

    @provide(scope=Scope.APP)
    def cache_service(self, cache: Cache) -> CacheService:
        return CacheService(cache)

    @provide(scope=Scope.REQUEST)
    async def session(
        self, factory: async_sessionmaker[AsyncSession]
    ) -> AsyncIterator[AsyncSession]:
        # Closing a session discards uncommitted work, so only explicit commits persist.
        async with factory() as session:
            yield session

    @provide(scope=Scope.REQUEST)
    def unit_of_work(self, session: AsyncSession) -> UnitOfWork:
        return SQLAlchemyUnitOfWork(session)
