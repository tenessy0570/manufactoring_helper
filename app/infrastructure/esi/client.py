from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta

import httpx

from app.infrastructure.http import ResilientHttpClient
from app.infrastructure.http.client import Sleep

ESI_DAY_OFFSET = timedelta(hours=11)  # the ESI date rolls over at 11:00 UTC


def get_current_compatibility_date(now: datetime) -> str:
    return (now.astimezone(UTC) - ESI_DAY_OFFSET).date().isoformat()


def make_compatibility_date_provider(
    configured: str, clock: Callable[[], datetime] = lambda: datetime.now(UTC)
) -> Callable[[], str]:
    """Returns a pinned date when configured, otherwise today's ESI date at call time."""
    if configured:
        return lambda: configured
    return lambda: get_current_compatibility_date(clock())


class EsiClient(ResilientHttpClient):
    """ESI transport: compatibility-date header plus back-pressure from rate-limit headers.

    See https://developers.eveonline.com/docs/services/esi/rate-limiting/ — routes under the new
    limiter report X-Ratelimit-*; the rest still use the legacy error limit (X-Esi-Error-Limit-*).
    """

    LOW_TOKENS_THRESHOLD = 5
    LOW_ERROR_LIMIT_THRESHOLD = 15
    BACK_PRESSURE_SECONDS = 2.0

    def __init__(
        self,
        http: httpx.AsyncClient,
        max_concurrency: int,
        max_retries: int,
        compatibility_date: Callable[[], str],
        sleep: Sleep | None = None,
    ) -> None:
        if sleep is None:
            super().__init__(http, max_concurrency, max_retries)
        else:
            super().__init__(http, max_concurrency, max_retries, sleep)
        self._compatibility_date = compatibility_date

    def _build_extra_headers(self) -> Mapping[str, str]:
        return {"X-Compatibility-Date": self._compatibility_date()}

    async def _handle_response(self, response: httpx.Response) -> None:
        tokens_low = self._is_running_low(
            response, "X-Ratelimit-Remaining", self.LOW_TOKENS_THRESHOLD
        )
        error_limit_low = self._is_running_low(
            response, "X-Esi-Error-Limit-Remain", self.LOW_ERROR_LIMIT_THRESHOLD
        )
        if tokens_low or error_limit_low:
            await self._sleep(self.BACK_PRESSURE_SECONDS)

    @staticmethod
    def _is_running_low(response: httpx.Response, header: str, threshold: int) -> bool:
        value = response.headers.get(header, "")
        return value.isdigit() and int(value) < threshold
