from dishka import AsyncContainer
from dishka.integrations.fastapi import setup_dishka
from fastapi import FastAPI

from app.core.config import Settings, get_settings
from app.core.di import create_container
from app.core.logging import configure_logging
from app.core.security import BasicAuthMiddleware
from app.domains.catalog.router import router as catalog_router
from app.domains.health.router import router as health_router
from app.domains.history.router import router as history_router
from app.domains.manufacturing.router import router as manufacturing_router
from app.domains.market.router import router as market_router


def create_app(
    container: AsyncContainer | None = None, settings: Settings | None = None
) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)
    container = container or create_container(settings)

    app = FastAPI(title="EVE Manufacturing")
    app.include_router(health_router)
    app.include_router(catalog_router)
    app.include_router(market_router)
    app.include_router(history_router)
    app.include_router(manufacturing_router)
    if settings.basic_auth_enabled:
        app.add_middleware(
            BasicAuthMiddleware,
            username=settings.basic_auth_username,
            password=settings.basic_auth_password.get_secret_value(),
        )
    setup_dishka(container, app)
    return app
