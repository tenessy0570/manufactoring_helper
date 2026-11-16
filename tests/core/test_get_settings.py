import pytest

from app.core.config import get_settings


def test_get_settings_reads_environment_and_is_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("POSTGRES_PASSWORD", "from-env")
    monkeypatch.setenv("REDIS_PASSWORD", "from-env")
    get_settings.cache_clear()

    first = get_settings()

    assert first.postgres_password.get_secret_value() == "from-env"
    assert get_settings() is first
    get_settings.cache_clear()
