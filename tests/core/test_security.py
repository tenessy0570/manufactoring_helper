import base64

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.security import BasicAuthMiddleware


def make_client() -> AsyncClient:
    app = FastAPI()

    @app.get("/secret")
    async def secret() -> dict[str, str]:
        return {"data": "secret"}

    @app.get("/health/live")
    async def live() -> dict[str, str]:
        return {"status": "ok"}

    app.add_middleware(BasicAuthMiddleware, username="admin", password="s3cret")
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def basic_header(raw: str) -> dict[str, str]:
    return {"Authorization": "Basic " + base64.b64encode(raw.encode()).decode()}


async def test_request_without_credentials_is_rejected_with_challenge() -> None:
    async with make_client() as client:
        response = await client.get("/secret")

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"].startswith("Basic")


async def test_valid_credentials_are_accepted() -> None:
    async with make_client() as client:
        response = await client.get("/secret", headers=basic_header("admin:s3cret"))

    assert response.status_code == 200


@pytest.mark.parametrize(
    "headers",
    [
        basic_header("admin:wrong"),
        basic_header("other:s3cret"),
        basic_header("no-separator"),
        {"Authorization": "Bearer token"},
        {"Authorization": "Basic !!!not-base64!!!"},
        {"Authorization": "Basic " + base64.b64encode(b"\xff\xfe:x").decode()},
    ],
)
async def test_invalid_credentials_are_rejected(headers: dict[str, str]) -> None:
    async with make_client() as client:
        response = await client.get("/secret", headers=headers)

    assert response.status_code == 401


async def test_health_endpoints_are_exempt_from_auth() -> None:
    async with make_client() as client:
        response = await client.get("/health/live")

    assert response.status_code == 200
