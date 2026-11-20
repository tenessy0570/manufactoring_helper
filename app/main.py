from dishka import AsyncContainer
from dishka.integrations.fastapi import setup_dishka
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.core.config import Settings, get_settings
from app.core.di import create_container
from app.core.logging import configure_logging
from app.core.security import BasicAuthMiddleware
from app.domains.accounts.middleware import SessionAuthMiddleware
from app.domains.accounts.router import router as account_router
from app.domains.accounts.service import AccountError
from app.domains.catalog.router import router as catalog_router
from app.domains.health.router import router as health_router
from app.domains.history.router import router as history_router
from app.domains.invention.router import router as invention_router
from app.domains.manufacturing.router import router as manufacturing_router
from app.domains.market.router import router as market_router
from app.domains.production.router import router as production_router
from app.domains.production.service import ProductionError
from app.domains.profiles.router import router as profile_router
from app.domains.trading.router import router as trading_router
from app.web.router import WEB_ROOT
from app.web.router import router as web_router


def create_app(
    container: AsyncContainer | None = None,
    settings: Settings | None = None,
    *,
    require_login: bool = True,
) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)
    container = container or create_container(settings)

    app = FastAPI(title="EVE Manufacturing")
    app.include_router(account_router)
    app.include_router(health_router)
    app.include_router(catalog_router)
    app.include_router(market_router)
    app.include_router(history_router)
    app.include_router(manufacturing_router)
    app.include_router(invention_router)
    app.include_router(profile_router)
    app.include_router(production_router)
    app.include_router(trading_router)
    app.include_router(web_router)
    app.mount("/static", StaticFiles(directory=str(WEB_ROOT / "static")), name="static")
    if require_login:
        app.add_middleware(SessionAuthMiddleware, container=container)
    elif settings.basic_auth_enabled:
        app.add_middleware(
            BasicAuthMiddleware,
            username=settings.basic_auth_username,
            password=settings.basic_auth_password.get_secret_value(),
        )

    @app.exception_handler(ProductionError)
    @app.exception_handler(AccountError)
    async def account_error(
        request: Request, error: AccountError | ProductionError
    ) -> JSONResponse:
        return JSONResponse({"detail": error.message}, status_code=error.status)

    setup_dishka(container, app)
    return app
