from datetime import UTC, datetime, timedelta


def get_refresh_deadline(synced_at: datetime, interval: timedelta) -> datetime:
    if synced_at.tzinfo is None:
        synced_at = synced_at.replace(tzinfo=UTC)
    return synced_at + interval
