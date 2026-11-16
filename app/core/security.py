import base64
import binascii
import secrets
from collections.abc import Awaitable, Callable, Iterable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp


class BasicAuthMiddleware(BaseHTTPMiddleware):
    """Protects every route with HTTP basic auth except the exempt path prefixes."""

    def __init__(
        self,
        app: ASGIApp,
        username: str,
        password: str,
        exempt_prefixes: Iterable[str] = ("/health",),
    ) -> None:
        super().__init__(app)
        self._username = username
        self._password = password
        self._exempt_prefixes = tuple(exempt_prefixes)

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if request.url.path.startswith(self._exempt_prefixes):
            return await call_next(request)
        if self._is_authorized(request.headers.get("Authorization")):
            return await call_next(request)
        return Response(
            status_code=401,
            content="Unauthorized",
            headers={"WWW-Authenticate": 'Basic realm="eve-manufacturing"'},
        )

    def _is_authorized(self, header: str | None) -> bool:
        credentials = self._parse_basic_header(header)
        if credentials is None:
            return False
        username, password = credentials
        username_ok = secrets.compare_digest(username.encode(), self._username.encode())
        password_ok = secrets.compare_digest(password.encode(), self._password.encode())
        return username_ok and password_ok

    @staticmethod
    def _parse_basic_header(header: str | None) -> tuple[str, str] | None:
        if not header:
            return None
        scheme, _, encoded = header.partition(" ")
        if scheme.lower() != "basic":
            return None
        try:
            decoded = base64.b64decode(encoded, validate=True).decode()
        except (binascii.Error, UnicodeDecodeError):
            return None
        username, separator, password = decoded.partition(":")
        return (username, password) if separator else None
