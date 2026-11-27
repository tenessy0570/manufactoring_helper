"""Public browser settings. Never add credentials or private infrastructure settings."""

from app.core.config import DEFAULT_REFRESH, RefreshPolicy

BROWSER_CONFIG = {
    "marketFreshnessMs": DEFAULT_REFRESH.market_seconds * 1000,
    "freshnessPollMs": 10000,
    "clockTickMs": 30000,
    "searchDebounceMs": 250,
}


def get_browser_settings(policy: RefreshPolicy = DEFAULT_REFRESH) -> dict[str, int]:
    return {**BROWSER_CONFIG, "marketFreshnessMs": policy.market_seconds * 1000}
