import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.core.application_errors import ApplicationError, ErrorKind
from app.infrastructure.http import HttpStatusError

logger = logging.getLogger(__name__)


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApplicationError)
    async def handle_application_error(request: Request, error: ApplicationError) -> JSONResponse:
        status = {
            ErrorKind.INVALID_OPERATION: 400,
            ErrorKind.INVALID_INPUT: 422,
            ErrorKind.UNAUTHENTICATED: 401,
            ErrorKind.FORBIDDEN: 403,
            ErrorKind.NOT_FOUND: 404,
            ErrorKind.CONFLICT: 409,
            ErrorKind.RATE_LIMITED: 429,
        }[error.kind]
        return JSONResponse({"detail": error.message}, status_code=status)

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, error: RequestValidationError
    ) -> JSONResponse:
        details = []
        for issue in error.errors():
            kind = issue["type"]
            message = (
                "Invalid value"
                if kind in ("value_error", "assertion_error", "json_invalid")
                else issue["msg"]
            )
            details.append({"loc": issue["loc"], "msg": message, "type": kind})
        return JSONResponse({"detail": details}, status_code=422)

    @app.exception_handler(HttpStatusError)
    async def handle_upstream_error(request: Request, error: HttpStatusError) -> JSONResponse:
        logger.warning(
            "Upstream request failed", exc_info=(type(error), error, error.__traceback__)
        )
        return JSONResponse(
            {"detail": "External data service is temporarily unavailable."}, status_code=502
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, error: Exception) -> JSONResponse:
        logger.error(
            "Unhandled request failure", exc_info=(type(error), error, error.__traceback__)
        )
        return JSONResponse(
            {"detail": "An internal error occurred. Please try again later."}, status_code=500
        )
