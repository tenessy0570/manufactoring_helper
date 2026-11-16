from functools import lru_cache
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL


class Settings(BaseSettings):
    """Infrastructure settings loaded from environment variables and an optional .env file."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_user: str = "eve"
    postgres_password: SecretStr
    postgres_db: str = "eve_manufacturing"

    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_password: SecretStr

    memory_cache_max_items: int = 10_000
    memory_cache_ttl_seconds: int = 60

    basic_auth_username: str = ""
    basic_auth_password: SecretStr = SecretStr("")

    @property
    def database_url(self) -> URL:
        return URL.create(
            drivername="postgresql+asyncpg",
            username=self.postgres_user,
            password=self.postgres_password.get_secret_value(),
            host=self.postgres_host,
            port=self.postgres_port,
            database=self.postgres_db,
        )

    @property
    def basic_auth_enabled(self) -> bool:
        return bool(self.basic_auth_username and self.basic_auth_password.get_secret_value())


@lru_cache
def get_settings() -> Settings:
    # Required fields are filled from the environment, which static analysis cannot see.
    return Settings()
