from abc import ABC, abstractmethod
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from email.utils import parsedate_to_datetime

from pydantic import TypeAdapter

from app.core.config import DEFAULT_REFRESH
from app.domains.history.models import HistoryDay, HistoryDownload
from app.infrastructure.esi import EsiClient
from app.infrastructure.http import HttpStatusError


class HistoryGateway(ABC):
    @abstractmethod
    async def fetch(self, region_id: int, type_id: int) -> HistoryDownload: ...


class EsiHistoryGateway(HistoryGateway):
    def __init__(
        self,
        esi: EsiClient,
        ttl_seconds: int = DEFAULT_REFRESH.history_seconds,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._esi, self._ttl, self._clock = esi, ttl_seconds, clock

    async def fetch(self, region_id: int, type_id: int) -> HistoryDownload:
        try:
            response = await self._esi.request(
                "GET", f"/markets/{region_id}/history/", params={"type_id": type_id}
            )
        except HttpStatusError as error:
            if error.status_code in (400, 404) and error.response is not None:
                try:
                    payload = error.response.json()
                except ValueError:
                    payload = None
                if (error.status_code == 404 and payload == {"error": "Type not found!"}) or (
                    error.status_code == 400
                    and payload == {"error": "Type not tradable on market!"}
                ):
                    return HistoryDownload(
                        days=[], expires_at=self._clock() + timedelta(seconds=self._ttl)
                    )
            raise
        expires_at = self._clock() + timedelta(seconds=self._ttl)
        if value := response.headers.get("Expires"):
            try:
                parsed = parsedate_to_datetime(value)
                parsed = parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed
                expires_at = min(expires_at, parsed)
            except (TypeError, ValueError):
                pass
        days = TypeAdapter(list[HistoryDay]).validate_python(response.json(parse_float=Decimal))
        if len({day.date for day in days}) != len(days):
            raise ValueError("Duplicate dates in regional history")
        return HistoryDownload(days=days, expires_at=expires_at)
