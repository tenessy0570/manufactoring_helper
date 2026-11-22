import pytest
from httpx import ASGITransport, AsyncClient

from app.main import create_app
from tests.helpers import make_settings


@pytest.mark.parametrize(
    "path",
    [
        "/",
        "/blueprint-calculator",
        "/interhub-trading",
        "/static/cargo.js",
        "/static/trading.js",
        "/static/history-chart.js",
        "/static/trading.css",
        "/static/app.css",
        "/static/app.js",
        "/static/calculator.css",
        "/static/vendor/alpine.min.js",
        "/static/vendor/htmx.min.js",
    ],
)
async def test_interface_and_bundled_assets_are_available(path: str) -> None:
    app = create_app(settings=make_settings(), require_login=False)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(path)
    assert response.status_code == 200
    if path == "/":
        assert '<html lang="en">' in response.text
        assert "Find your next build" in response.text
    if path == "/blueprint-calculator":
        assert 'id="calculator-form"' in response.text
        assert "Manufacturing runs" in response.text
        assert "Manufacturing output" in response.text
        assert "Min. margin" not in response.text
        assert "Rows per page" not in response.text


async def test_interface_requires_configured_authentication() -> None:
    app = create_app(
        settings=make_settings(basic_auth_username="admin", basic_auth_password="secret"),
        require_login=False,
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/")
    assert response.status_code == 401


async def test_cargo_page_and_api_temporarily_disabled() -> None:
    app = create_app(settings=make_settings(), require_login=False)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.get("/cargo-planner")).status_code == 404
        assert (await client.post("/api/v1/trading/cargo", json={})).status_code == 404
        assert "/cargo-planner" not in (await client.get("/")).text
