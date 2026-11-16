import pytest
from pydantic import ValidationError

from tests.helpers import make_settings


def test_database_url_uses_asyncpg_driver_and_settings_values() -> None:
    settings = make_settings(
        postgres_user="user", postgres_host="db", postgres_port=5433, postgres_db="eve"
    )

    url = settings.database_url

    assert url.drivername == "postgresql+asyncpg"
    assert (url.username, url.host, url.port, url.database) == ("user", "db", 5433, "eve")
    assert url.password == "pg-secret"


def test_database_url_keeps_special_characters_in_password_intact() -> None:
    settings = make_settings(postgres_password="p@ss:/word#1")

    assert settings.database_url.password == "p@ss:/word#1"


def test_basic_auth_is_disabled_by_default() -> None:
    assert make_settings().basic_auth_enabled is False


def test_basic_auth_requires_both_username_and_password() -> None:
    assert make_settings(basic_auth_username="admin").basic_auth_enabled is False
    assert make_settings(basic_auth_password="secret").basic_auth_enabled is False
    assert make_settings(
        basic_auth_username="admin", basic_auth_password="secret"
    ).basic_auth_enabled


def test_passwords_are_required() -> None:
    with pytest.raises(ValidationError):
        make_settings(postgres_password=None)


def test_unknown_log_level_is_rejected() -> None:
    with pytest.raises(ValidationError):
        make_settings(log_level="LOUD")
