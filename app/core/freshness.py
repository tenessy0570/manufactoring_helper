from datetime import UTC, datetime, timedelta

MARKET_REFRESH_MINUTES = 20
MARKET_FRESHNESS = timedelta(minutes=MARKET_REFRESH_MINUTES)
HISTORY_FRESHNESS = timedelta(days=1)


def refresh_deadline(synced_at: datetime, interval: timedelta) -> datetime:
    if synced_at.tzinfo is None:
        synced_at = synced_at.replace(tzinfo=UTC)
    return synced_at + interval
