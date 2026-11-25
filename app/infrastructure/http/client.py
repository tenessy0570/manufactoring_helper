import asyncio
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

import httpx

Sleep = Callable[[float], Awaitable[None]]


class HttpStatusError(Exception):
    def __init__(self, status_code: int, url: str, response: httpx.Response | None = None) -> None:
        super().__init__(f"HTTP {status_code} for {url}")
        self.status_code = status_code
        self.url = url
        self.response = response


class ResilientHttpClient:
    """HTTP client with bounded concurrency and retries for transient failures.

    Subclasses customise behaviour through two hooks: `_extra_headers` (added to every request)
    and `_on_response` (called after every response, may sleep to apply back-pressure).
    """

    RETRY_STATUSES = frozenset({420, 429, 500, 502, 503, 504})
    MAX_BACKOFF_SECONDS = 30.0

    def __init__(
        self,
        http: httpx.AsyncClient,
        max_concurrency: int,
        max_retries: int,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        if max_concurrency <= 0:
            raise ValueError("max_concurrency must be positive")
        if max_retries < 0:
            raise ValueError("max_retries must be non-negative")
        self._http = http
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._max_retries = max_retries
        self._sleep = sleep

    async def aclose(self) -> None:
        await self._http.aclose()

    async def get_json(self, path: str, params: Mapping[str, Any] | None = None) -> Any:
        return (await self.request("GET", path, params=params)).json()

    async def post_json(self, path: str, body: Any) -> Any:
        return (await self.request("POST", path, json=body)).json()

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json: Any = None,
    ) -> httpx.Response:
        for attempt in range(self._max_retries + 1):
            is_last_attempt = attempt == self._max_retries
            try:
                response = await self._send(method, path, params, json)
            except httpx.TransportError:
                if is_last_attempt:
                    raise
                await self._sleep(self._calculate_backoff(attempt))
                continue
            if response.is_success:
                return response
            if response.status_code in self.RETRY_STATUSES and not is_last_attempt:
                await self._sleep(self._get_retry_delay(response, attempt))
                continue
            raise HttpStatusError(response.status_code, str(response.url), response)
        raise AssertionError("unreachable: the last attempt always returns or raises")

    def _build_extra_headers(self) -> Mapping[str, str]:
        return {}

    async def _handle_response(self, response: httpx.Response) -> None:
        return None

    async def _send(
        self, method: str, path: str, params: Mapping[str, Any] | None, json: Any
    ) -> httpx.Response:
        async with self._semaphore:
            response = await self._http.request(
                method, path, params=params, json=json, headers=self._build_extra_headers()
            )
            # Runs while holding a concurrency slot, so a back-pressure sleep slows every caller.
            await self._handle_response(response)
            return response

    def _get_retry_delay(self, response: httpx.Response, attempt: int) -> float:
        retry_after = response.headers.get("Retry-After", "")
        if retry_after.isdigit():
            return float(retry_after)
        return self._calculate_backoff(attempt)

    def _calculate_backoff(self, attempt: int) -> float:
        return min(2.0**attempt, self.MAX_BACKOFF_SECONDS)
