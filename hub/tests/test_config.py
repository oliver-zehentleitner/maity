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
    assert settings.seal_verifiers is False


def test_sealing_verifiers_is_opt_in_and_needs_the_key() -> None:
    """MAITY_SEAL_VERIFIERS (docs/api.md §2.2): off by default, also with a key."""
    key = "q0bS0b3k1uN4b9dW8m2Yx5zR7cJ6vT1eH3gK8pL0aQs="
    assert Settings.from_env({"MAITY_SECRET_KEY": key}).seal_verifiers is False
    on = {"MAITY_SECRET_KEY": key, "MAITY_SEAL_VERIFIERS": "1"}
    assert Settings.from_env(on).seal_verifiers is True
    assert Settings.from_env({**on, "MAITY_SEAL_VERIFIERS": "0"}).seal_verifiers is False
    with pytest.raises(ConfigError, match="MAITY_SEAL_VERIFIERS=1 needs MAITY_SECRET_KEY"):
        Settings.from_env({"MAITY_SEAL_VERIFIERS": "1"})
    with pytest.raises(ConfigError, match="MAITY_SEAL_VERIFIERS must be 1 or 0"):
        Settings.from_env({**on, "MAITY_SEAL_VERIFIERS": "maybe"})


def test_sealed_verifiers_only_is_off_by_default_and_needs_sealing() -> None:
    """MAITY_SEALED_VERIFIERS_ONLY (§2.2): off by default, also with sealing on; on, it needs
    sealing on, or every new join would write a plain row and be refused at once."""
    key = "q0bS0b3k1uN4b9dW8m2Yx5zR7cJ6vT1eH3gK8pL0aQs="
    on = {"MAITY_SECRET_KEY": key, "MAITY_SEAL_VERIFIERS": "1"}
    assert Settings.from_env({}).sealed_verifiers_only is False
    assert Settings.from_env(on).sealed_verifiers_only is False
    only = {**on, "MAITY_SEALED_VERIFIERS_ONLY": "1"}
    assert Settings.from_env(only).sealed_verifiers_only is True
    needs = "MAITY_SEALED_VERIFIERS_ONLY=1 needs MAITY_SEAL_VERIFIERS=1 and MAITY_SECRET_KEY"
    for env in (
        {"MAITY_SECRET_KEY": key, "MAITY_SEALED_VERIFIERS_ONLY": "1"},
        {**only, "MAITY_SEAL_VERIFIERS": "0"},
    ):
        with pytest.raises(ConfigError, match=needs):
            Settings.from_env(env)
    with pytest.raises(ConfigError, match="MAITY_SEALED_VERIFIERS_ONLY must be 1 or 0"):
        Settings.from_env({**on, "MAITY_SEALED_VERIFIERS_ONLY": "maybe"})


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


@pytest.mark.wheel
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


@pytest.mark.parametrize(
    "url",
    [
        "postgresql://maity@db/maity?password=s3cret-q",
        "postgresql://maity@db/maity?PASSWORD=s3cret-q",
        "postgresql://maity@db/maity?pass%77ord=s3cret-q",
        "postgresql://maity@db/maity?sslmode=require&sslpassword=s3cret-q",
        "postgresql://maity@db/maity?passfile=/run/s3cret-q",
        "mariadb://maity@db/maity?passwd=s3cret-q",
        "mariadb://maity@db/maity?password=s3cret-q&password=s3cret-q",
        "postgresql://maity:pw@db/maity?options=-c%20password%3Ds3cret-q",
    ],
)
def test_redaction_leaves_the_query_string_out(url: str) -> None:
    """The drivers take a password in the query string too, under several names and in
    percent-encoded forms, and any other key can carry a secret; the redaction shows none of the
    query, only that there was one."""
    shown = redact_database_url(normalize_database_url(url))
    assert shown.endswith("@db/maity?***"), shown
    assert "s3cret" not in shown and "pass" not in shown.lower()


def test_redaction_of_a_url_without_a_query_adds_no_mark() -> None:
    assert redact_database_url("sqlite:///maity-hub.db") == "sqlite:///maity-hub.db"


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


@pytest.mark.wheel
def test_the_wheel_carries_the_dashboard_from_web() -> None:
    import ast

    hub = Path(__file__).resolve().parents[1]
    tree = ast.parse((hub / "hatch_build.py").read_text())
    (bundled,) = (
        ast.literal_eval(node.value)
        for node in tree.body
        if isinstance(node, ast.Assign) and ast.unparse(node.targets[0]) == "BUNDLED"
    )
    web = {k: v for k, v in bundled.items() if v.startswith("maity_hub/web")}
    assert "maity_hub/web/index.html" in web.values()
    for source in web:
        assert (hub.parent / source).exists(), source
        assert not {"fixtures", "tools", "context"} & set(Path(source).parts)
