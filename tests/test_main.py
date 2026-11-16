import base64

from httpx import ASGITransport, AsyncClient

from app.main import create_app
from tests.helpers import make_settings


def make_client(**settings_overrides: object) -> AsyncClient:
    app = create_app(settings=make_settings(**settings_overrides))
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_app_is_open_when_basic_auth_is_not_configured() -> None:
    async with make_client() as client:
        response = await client.get("/health/live")

    assert response.status_code == 200


async def test_app_requires_credentials_when_basic_auth_is_configured() -> None:
    async with make_client(basic_auth_username="admin", basic_auth_password="s3cret") as client:
        unauthorized = await client.get("/unknown")
        authorized = await client.get(
            "/unknown",
            headers={"Authorization": "Basic " + base64.b64encode(b"admin:s3cret").decode()},
        )
        health = await client.get("/health/live")

    assert unauthorized.status_code == 401
    assert authorized.status_code == 404
    assert health.status_code == 200
