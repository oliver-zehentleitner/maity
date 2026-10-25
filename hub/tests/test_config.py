from __future__ import annotations

from pathlib import Path

import pytest

from maity_hub import config
from maity_hub.config import (
    DEFAULT_DATABASE_URL,
    ConfigError,
    Settings,
    normalize_database_url,
    parse_bind,
    redact_database_url,
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


@pytest.mark.parametrize(
    ("bind", "public_url", "guessed"),
    [
        ("127.0.0.1:8080", "http://127.0.0.1:8080", False),
        ("[::1]:8080", "http://[::1]:8080", False),
        ("0.0.0.0:8080", "http://localhost:8080", True),
        ("[::]:9000", "http://localhost:9000", True),
        ("hub.internal:80", "http://hub.internal:80", False),
    ],
)
def test_public_url_derived_from_the_bind(bind: str, public_url: str, guessed: bool) -> None:
    settings = Settings.from_env({"MAITY_BIND": bind})
    assert (settings.public_url, settings.public_url_guessed) == (public_url, guessed)


def test_an_explicit_public_url_is_never_a_guess() -> None:
    settings = Settings.from_env(
        {"MAITY_BIND": "0.0.0.0:8080", "MAITY_PUBLIC_URL": "https://hub.example"}
    )
    assert (settings.public_url, settings.public_url_guessed) == ("https://hub.example", False)


def test_the_dashboard_default_is_the_checkouts_or_the_packages() -> None:
    web_dir = Settings.from_env({}).web_dir
    if Path(config.__file__).resolve().parent.parent.name == "src":
        assert web_dir == Path(__file__).resolve().parents[2] / "web"
    else:  # an installed wheel carries the dashboard itself
        assert web_dir == Path(config.__file__).resolve().parent / "web"
    assert web_dir is not None and (web_dir / "index.html").is_file()


def test_redaction_masks_the_password() -> None:
    url = normalize_database_url("postgresql://maity:pw@db/maity")
    assert redact_database_url(url) == "postgresql+psycopg://maity:***@db/maity"


def test_public_url_loses_its_trailing_slash() -> None:
    assert Settings.from_env({"MAITY_PUBLIC_URL": "https://hub.example/"}).public_url == (
        "https://hub.example"
    )


def test_an_installed_package_serves_the_dashboard_it_carries(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    package = tmp_path / "site-packages" / "maity_hub"
    package.mkdir(parents=True)
    monkeypatch.setattr(config, "__file__", str(package / "config.py"))
    assert config.checkout_web_dir() is None  # a package without the dashboard: API only
    (package / "web").mkdir()
    (package / "web" / "index.html").write_text("<!doctype html>")
    assert config.checkout_web_dir() == package / "web"


def test_the_wheel_carries_the_dashboard_from_web() -> None:
    import tomllib

    hub = Path(__file__).resolve().parents[1]
    pyproject = tomllib.loads((hub / "pyproject.toml").read_text())
    included = pyproject["tool"]["hatch"]["build"]["targets"]["wheel"]["force-include"]
    web = {k: v for k, v in included.items() if v.startswith("maity_hub/web")}
    assert "maity_hub/web/index.html" in web.values()
    for source in web:
        assert (hub / source).exists(), source
        assert not {"fixtures", "tools", "context"} & set(Path(source).parts)
