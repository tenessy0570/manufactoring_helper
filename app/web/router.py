from pathlib import Path

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.domains.health.models import HealthStatus
from app.domains.health.service import HealthService

WEB_ROOT = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(WEB_ROOT / "templates"))
router = APIRouter(route_class=DishkaRoute, include_in_schema=False)


@router.get("/", response_class=HTMLResponse)
async def home(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request=request, name="index.html")


@router.get("/blueprint-calculator", response_class=HTMLResponse)
async def blueprint_calculator(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request=request, name="calculator.html")


@router.get("/ui/status", response_class=HTMLResponse)
async def status(request: Request, service: FromDishka[HealthService]) -> HTMLResponse:
    report = await service.readiness()
    return templates.TemplateResponse(
        request=request,
        name="status.html",
        context={
            "healthy": report.status == HealthStatus.OK,
        },
    )


@router.get("/invention-shopping", response_class=HTMLResponse)
async def invention_shopping(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request=request, name="shopping.html")


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request, name="account.html", context={"mode": "login"}
    )


@router.get("/account", response_class=HTMLResponse)
async def account_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request, name="account.html", context={"mode": "account"}
    )


@router.get("/admin", response_class=HTMLResponse)
async def admin_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request, name="account.html", context={"mode": "admin"}
    )


@router.get("/production-history", response_class=HTMLResponse)
async def production_history(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request=request, name="production.html")
