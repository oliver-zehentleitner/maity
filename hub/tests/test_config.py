from __future__ import annotations

import pytest

from maity_hub.config import (
    DEFAULT_DATABASE_URL,
    ConfigError,
    Settings,
    normalize_database_url,
    parse_bind,
)


def test_defaults() -> None:
    settings = Settings.from_env({})
    assert settings.database_url == DEFAULT_DATABASE_URL
    assert (settings.host, settings.port) == ("127.0.0.1", 8080)
    assert settings.public_url == "http://127.0.0.1:8080"
    assert settings.web_dir_required is False


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("postgresql://u:p@db/maity", "postgresql+psycopg://u:p@db/maity"),
        ("postgres://u:p@db/maity", "postgresql+psycopg://u:p@db/maity"),
        ("mysql://u:p@db/maity", "mysql+pymysql://u:p@db/maity"),
        ("mariadb://u:p@db/maity", "mariadb+pymysql://u:p@db/maity"),
        ("postgresql+psycopg://u@db/m", "postgresql+psycopg://u@db/m"),
        ("sqlite:///hub.db", "sqlite:///hub.db"),
    ],
)
def test_database_url_gets_the_shipped_driver(url: str, expected: str) -> None:
    assert normalize_database_url(url) == expected


def test_bind_parsing() -> None:
    assert parse_bind("0.0.0.0:9000") == ("0.0.0.0", 9000)
    assert parse_bind("[::1]:8080") == ("::1", 8080)
    with pytest.raises(ConfigError):
        parse_bind("8080")


def test_public_url_loses_its_trailing_slash() -> None:
    assert Settings.from_env({"MAITY_PUBLIC_URL": "https://hub.example/"}).public_url == (
        "https://hub.example"
    )
