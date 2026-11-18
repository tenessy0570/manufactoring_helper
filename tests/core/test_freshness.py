from datetime import UTC, datetime, timedelta

from app.core.freshness import HISTORY_FRESHNESS, MARKET_FRESHNESS, refresh_deadline


def test_snapshot_deadlines_use_refresh_policy_and_normalize_sqlite_time() -> None:
    synced = datetime(2026, 11, 19, 10, tzinfo=UTC)
    assert refresh_deadline(synced, MARKET_FRESHNESS) == synced + timedelta(minutes=20)
    assert refresh_deadline(synced.replace(tzinfo=None), HISTORY_FRESHNESS) == synced + timedelta(
        days=1
    )
