import json
from pathlib import Path

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates

from app.core.config import DEFAULT_REFRESH
from app.domains.health.models import HealthStatus
from app.domains.health.service import HealthService
from app.web.config import get_browser_settings

WEB_ROOT = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(WEB_ROOT / "templates"))
router = APIRouter(route_class=DishkaRoute, include_in_schema=False)


@router.get("/", response_class=HTMLResponse, name="home")
async def get_opportunities_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request=request, name="index.html")


@router.get("/blueprint-calculator", response_class=HTMLResponse, name="blueprint_calculator")
async def get_blueprint_calculator_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request=request, name="calculator.html")


@router.get("/ui/status", response_class=HTMLResponse, name="status")
async def get_status_page(request: Request, service: FromDishka[HealthService]) -> HTMLResponse:
    report = await service.check_readiness()
    return templates.TemplateResponse(
        request=request,
        name="status.html",
        context={
            "healthy": report.status == HealthStatus.OK,
        },
    )


@router.get("/invention-shopping", response_class=HTMLResponse, name="invention_shopping")
async def get_invention_shopping_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request=request, name="shopping.html")


@router.get("/login", response_class=HTMLResponse, name="login_page")
async def get_login_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request, name="account.html", context={"mode": "login"}
    )


@router.get("/account", response_class=HTMLResponse, name="account_page")
async def get_account_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request, name="account.html", context={"mode": "account"}
    )


@router.get("/admin", response_class=HTMLResponse, name="admin_page")
async def get_admin_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request, name="account.html", context={"mode": "admin"}
    )


@router.get("/production-history", response_class=HTMLResponse, name="production_history")
async def get_production_history_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request=request, name="production.html")


@router.get("/interhub-trading", response_class=HTMLResponse, name="interhub_trading")
async def get_interhub_trading_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request=request, name="trading.html")


# Temporarily disabled pending Cargo planner redesign.
# @router.get("/cargo-planner", response_class=HTMLResponse)
# async def cargo_planner(request: Request) -> HTMLResponse:
#     return templates.TemplateResponse(request=request, name="cargo.html")


@router.get("/ui/config.js", name="browser_config")
async def get_browser_config_script(request: Request) -> Response:
    # Explicit public allowlist; never serialize Settings into a browser response.
    return Response(
        "window.eveConfig = Object.freeze("
        + json.dumps(
            get_browser_settings(getattr(request.app.state, "refresh_policy", DEFAULT_REFRESH))
        )
        + ");",
        media_type="application/javascript",
    )
