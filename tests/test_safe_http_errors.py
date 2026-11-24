import httpx
import pytest

from app.infrastructure.http import HttpStatusError
from app.main import create_app
from tests.helpers import make_settings

SECRET = "test-secret-must-not-be-returned"


@pytest.mark.parametrize(
    ("kind", "status"), [("internal", 500), ("upstream", 502), ("response", 500)]
)
async def test_failure_responses_do_not_expose_internal_details(kind: str, status: int) -> None:
    app = create_app(settings=make_settings(), require_login=False)

    @app.get("/test/failure", response_model=int)
    async def failure() -> str:
        if kind == "upstream":
            raise HttpStatusError(500, "https://private.invalid/?token=" + SECRET)
        if kind == "response":
            return SECRET
        raise RuntimeError("postgresql://user:" + SECRET + "@private/db SELECT password_hash")

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app, raise_app_exceptions=False), base_url="http://test"
    ) as client:
        response = await client.get("/test/failure")
        assert response.status_code == status
        for value in (SECRET, "postgresql", "password_hash", "private.invalid", "Traceback"):
            assert value not in response.text
        assert isinstance(response.json()["detail"], str)


async def test_validation_response_omits_password_input_and_context() -> None:
    app = create_app(settings=make_settings(), require_login=False)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/v1/accounts/login",
            json={"username": "valid_user", "password": {"secret": SECRET}},
        )
        assert response.status_code == 422
        assert SECRET not in response.text
        assert all(set(issue) == {"loc", "msg", "type"} for issue in response.json()["detail"])


@pytest.mark.parametrize("kind", ["value_error", "assertion_error", "json_invalid"])
async def test_custom_validation_error_cannot_echo_internal_message(kind: str) -> None:
    from fastapi.exceptions import RequestValidationError

    app = create_app(settings=make_settings(), require_login=False)

    @app.get("/test/validation")
    async def failure() -> None:
        raise RequestValidationError(
            [
                {
                    "loc": ["body", "password"],
                    "type": kind,
                    "msg": SECRET,
                    "input": SECRET,
                    "ctx": {"secret": SECRET},
                }
            ]
        )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://test"
    ) as client:
        response = await client.get("/test/validation")
        assert response.status_code == 422
        assert SECRET not in response.text
