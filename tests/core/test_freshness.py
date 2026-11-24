from datetime import UTC, datetime, timedelta

from app.core.config import DEFAULT_REFRESH
from app.core.freshness import refresh_deadline


def test_snapshot_deadlines_use_refresh_policy_and_normalize_sqlite_time() -> None:
    synced = datetime(2026, 11, 19, 10, tzinfo=UTC)
    assert refresh_deadline(synced, DEFAULT_REFRESH.market) == synced + timedelta(minutes=20)
    assert refresh_deadline(
        synced.replace(tzinfo=None), DEFAULT_REFRESH.history
    ) == synced + timedelta(days=1)
