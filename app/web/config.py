"""Public browser settings. Never add credentials or private infrastructure settings."""

from app.core.freshness import MARKET_FRESHNESS

BROWSER_CONFIG = {
    "marketFreshnessMs": int(MARKET_FRESHNESS.total_seconds() * 1000),
    "freshnessPollMs": 60000,
    "clockTickMs": 30000,
    "searchDebounceMs": 250,
}
