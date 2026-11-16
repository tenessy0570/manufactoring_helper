from pydantic import JsonValue

from app.core.cache import Cache
from app.core.config import Settings


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class FailingCache(Cache):
    async def get(self, key: str) -> JsonValue | None:
        raise ConnectionError("cache is down")

    async def set(self, key: str, value: JsonValue, ttl_seconds: int) -> None:
        raise ConnectionError("cache is down")

    async def delete(self, key: str) -> None:
        raise ConnectionError("cache is down")


def make_settings(**overrides: object) -> Settings:
    """Builds Settings from explicit values only, ignoring the environment and .env."""
    values: dict[str, object] = {
        "postgres_password": "pg-secret",
        "redis_password": "redis-secret",
        **overrides,
    }
    return Settings.model_validate(values)
