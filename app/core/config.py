from datetime import timedelta
from functools import lru_cache
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL


class RefreshPolicy(BaseModel):
    """Shared refresh intervals used by workers, calculations and freshness reports."""

    model_config = ConfigDict(frozen=True)
    market_seconds: int = Field(default=1200, ge=1)
    history_retention_months: int = Field(default=12, ge=1, le=120)
    history_seconds: int = Field(default=86400, ge=3600, le=86400)
    recipe_seconds: int = Field(default=86400, ge=3600, le=604800)
    invention_price_seconds: int = Field(default=86400, ge=1)
    invention_plan_seconds: int = Field(default=604800, ge=3600, le=2592000)
    metadata_seconds: int = Field(default=604800, ge=1)
    retry_seconds: int = Field(default=300, ge=1)

    @property
    def market(self) -> timedelta:
        return timedelta(seconds=self.market_seconds)

    @property
    def history(self) -> timedelta:
        return timedelta(seconds=self.history_seconds)


DEFAULT_REFRESH = RefreshPolicy()


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

    esi_base_url: str = "https://esi.evetech.net"
    # CCP asks for a User-Agent that identifies the app and a way to contact its owner.
    esi_user_agent: str = "eve-manufacturing"
    # Empty means "today's ESI date", derived from the clock (the ESI day rolls over at 11:00 UTC).
    esi_compatibility_date: str = ""
    esi_max_concurrency: int = 20

    everef_base_url: str = "https://ref-data.everef.net"
    everef_max_concurrency: int = 20

    http_timeout_seconds: float = 30.0
    http_max_retries: int = 4

    catalog_max_age_hours: int = 20
    market_refresh_seconds: int = Field(default=DEFAULT_REFRESH.market_seconds, ge=1)
    market_cache_seconds: int = Field(default=300, ge=1, le=3600)
    history_retention_months: int = Field(
        default=DEFAULT_REFRESH.history_retention_months, ge=1, le=120
    )
    history_cache_seconds: int = Field(default=DEFAULT_REFRESH.history_seconds, ge=3600, le=86400)
    industry_base_url: str = "https://api.everef.net"
    industry_max_concurrency: int = Field(default=3, ge=1, le=20)
    manufacturing_cache_seconds: int = Field(
        default=DEFAULT_REFRESH.recipe_seconds, ge=3600, le=604800
    )
    invention_plan_ttl_seconds: int = Field(
        default=DEFAULT_REFRESH.invention_plan_seconds, ge=3600, le=2592000
    )

    invention_price_ttl_seconds: int = Field(default=DEFAULT_REFRESH.invention_price_seconds, ge=1)
    trading_metadata_ttl_seconds: int = Field(default=DEFAULT_REFRESH.metadata_seconds, ge=1)
    refresh_retry_seconds: int = Field(default=DEFAULT_REFRESH.retry_seconds, ge=1)

    session_ttl_seconds: int = Field(default=1209600, ge=60)
    item_names_cache_seconds: int = Field(default=604800, ge=1)
    route_cache_seconds: int = Field(default=86400, ge=1)
    route_error_cache_seconds: int = Field(default=300, ge=1)

    basic_auth_username: str = ""
    basic_auth_password: SecretStr = SecretStr("")

    @property
    def refresh_policy(self) -> RefreshPolicy:
        return RefreshPolicy(
            market_seconds=self.market_refresh_seconds,
            history_seconds=self.history_cache_seconds,
            history_retention_months=self.history_retention_months,
            recipe_seconds=self.manufacturing_cache_seconds,
            invention_price_seconds=self.invention_price_ttl_seconds,
            invention_plan_seconds=self.invention_plan_ttl_seconds,
            metadata_seconds=self.trading_metadata_ttl_seconds,
            retry_seconds=self.refresh_retry_seconds,
        )

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
