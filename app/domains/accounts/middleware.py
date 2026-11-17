from collections.abc import Awaitable, Callable
from urllib.parse import quote

from dishka import AsyncContainer
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, RedirectResponse
from starlette.types import ASGIApp

from app.domains.accounts.service import COOKIE_NAME, AccountService


class SessionAuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp, container: AsyncContainer) -> None:
        super().__init__(app)
        self.container = container

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        path = request.url.path
        public = path in (
            "/login",
            "/api/v1/accounts/login",
            "/health/live",
            "/health/ready",
        ) or path.startswith("/static/")
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            origin = request.headers.get("origin")
            if request.headers.get("x-requested-with") != "XMLHttpRequest" or (
                origin is not None and origin.rstrip("/") != str(request.base_url).rstrip("/")
            ):
                return JSONResponse({"detail": "Invalid request origin"}, status_code=403)
        if public:
            return await call_next(request)
        token = request.cookies.get(COOKIE_NAME, "")
        user = None
        if token and len(token) <= 128:
            async with self.container() as scope:
                user = await (await scope.get(AccountService)).identity(token)
        if user is None:
            if path.startswith("/api/") or path.startswith("/health/"):
                return JSONResponse({"detail": "Login required"}, status_code=401)
            return RedirectResponse("/login?next=" + quote(path, safe=""), status_code=303)
        if (
            path.startswith("/admin") or path.startswith("/api/v1/accounts/users")
        ) and not user.is_superuser:
            return JSONResponse({"detail": "Superuser access required"}, status_code=403)
        request.state.user = user
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        return response
