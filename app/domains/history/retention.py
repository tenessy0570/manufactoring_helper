from calendar import monthrange
from datetime import UTC, date, datetime


def retention_cutoff(now: datetime, months: int) -> date:
    today = now.replace(tzinfo=UTC).date() if now.tzinfo is None else now.astimezone(UTC).date()
    year, month = divmod(today.year * 12 + today.month - 1 - months, 12)
    month += 1
    return date(year, month, min(today.day, monthrange(year, month)[1]))
