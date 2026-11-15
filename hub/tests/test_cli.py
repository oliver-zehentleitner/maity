from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from maity_hub.cli import main
from maity_hub.db import head_revision, make_engine

PASSWORD = "s3cret-pw"
ACCOUNT_PASSWORD = "correct-horse-battery-staple"


def head() -> str | None:
    """The head of the migrations the package carries: a number or a UTC time and a slug."""
    engine = make_engine("sqlite://")
    try:
        return head_revision(engine)
    finally:
        engine.dispose()


@pytest.fixture(autouse=True)
def isolated_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    for name in ("MAITY_DATABASE_URL", "MAITY_BIND", "MAITY_PUBLIC_URL", "MAITY_WEB_DIR"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)


@pytest.mark.wheel
def test_migrate_then_report(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["migrate"]) == 0
    assert capsys.readouterr().out.strip().endswith(f"schema empty -> {head()}")
    assert Path("maity-hub.db").is_file()


def test_a_migrate_that_gives_up_says_where_the_schema_stays(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from sqlalchemy.exc import OperationalError

    import maity_hub.cli

    def deadlocked(_engine: object, **_options: object) -> None:
        raise OperationalError("ALTER TABLE", {}, Exception("deadlock detected"))

    monkeypatch.setattr(maity_hub.cli, "migrate", deadlocked)
    assert main(["migrate"]) == 1
    err = capsys.readouterr().err.splitlines()
    assert err[0] == f"maity-hub: schema stays at empty, head {head()} not reached"
    assert err[1].endswith(": deadlock detected")


def test_migrate_hands_the_instance_key_to_the_migrations(monkeypatch: pytest.MonkeyPatch) -> None:
    """The migration that seals the credentials' verifiers needs the key (docs/api.md §2.2)."""
    import base64

    import maity_hub.cli

    key = bytes(range(32))
    handed: list[object] = []
    monkeypatch.setenv("MAITY_SECRET_KEY", base64.b64encode(key).decode())
    monkeypatch.setattr(
        maity_hub.cli, "migrate", lambda _engine, **options: handed.append(options["secret_key"])
    )
    assert main(["migrate"]) == 0
    assert handed == [key]


@pytest.mark.wheel
def test_the_installed_entry_point_answers() -> None:
    """The console script the package declares is on the path and starts the hub's CLI."""
    import os
    import shutil
    import subprocess

    from maity_hub import __version__

    script = shutil.which("maity-hub")
    if script is None and not os.environ.get("CI"):  # CI installs it: there, missing is a failure
        pytest.skip("maity-hub is not on the path: `make install` in a venv (hub/README.md)")
    assert script is not None
    result = subprocess.run([script, "--version"], capture_output=True, text=True, check=True)
    assert result.stdout.strip() == f"maity-hub {__version__}"


def test_serve_refuses_an_unmigrated_database(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["serve"]) == 1
    assert "run `maity-hub migrate` first" in capsys.readouterr().err


def test_serve_reports_a_bad_web_dir_in_one_line(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["migrate"]) == 0
    monkeypatch.setenv("MAITY_WEB_DIR", "/nonexistent/web")
    assert main(["serve"]) == 2
    err = capsys.readouterr().err
    assert err.count("\n") == 1
    assert "MAITY_WEB_DIR" in err


def test_an_invalid_database_url_is_not_echoed(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("MAITY_DATABASE_URL", f"postgresql//maity:{PASSWORD}@db/maity")
    assert main(["migrate"]) == 2
    err = capsys.readouterr().err
    assert "MAITY_DATABASE_URL" in err
    assert PASSWORD not in err
    assert "s3cr" not in err


@pytest.mark.parametrize(
    "url",
    [
        "postgresql://maity:s3cr@t-pw@db/maity",  # the tail would be the host
        "postgresql://maity:s3cr@t:pw@db/maity",  # ... or a non-numeric port
        "postgresql://maity:s3cr@t/pw@db/maity",  # ... or the database name
        "postgresql://maity:s3cr@db/maity?x=t@pw",  # ... or the query
    ],
)
def test_an_unencoded_at_in_the_password_is_refused_without_echo(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], url: str
) -> None:
    monkeypatch.setenv("MAITY_DATABASE_URL", url)
    assert main(["migrate"]) == 2
    err = capsys.readouterr().err
    assert err.count("\n") == 1
    assert "percent-encoded" in err
    assert "s3cr" not in err
    assert "pw" not in err


def test_a_non_numeric_port_is_refused_without_echo(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("MAITY_DATABASE_URL", "postgresql://maity:s3cret@db:x5432/maity")
    assert main(["migrate"]) == 2
    err = capsys.readouterr().err
    assert err == "maity-hub: MAITY_DATABASE_URL is not a valid database URL\n"


@pytest.mark.parametrize("command", ["migrate", "serve"])
@pytest.mark.parametrize(
    ("url", "reason"),
    [
        ("foo://x/y", "Can't load plugin"),  # unknown dialect
        ("postgresql+psycopg2://maity:s3cret@db/maity", "psycopg2"),  # driver not installed
    ],
)
def test_an_unusable_dialect_or_driver_fails_in_one_line(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    command: str,
    url: str,
    reason: str,
) -> None:
    monkeypatch.setenv("MAITY_DATABASE_URL", url)
    assert main([command]) == 1
    err = capsys.readouterr().err
    assert err.count("\n") == 1
    assert reason in err
    assert "s3cret" not in err


@pytest.mark.parametrize("command", ["migrate", "serve"])
def test_an_unreachable_database_fails_in_one_line_without_the_password(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], command: str
) -> None:
    monkeypatch.setenv("MAITY_DATABASE_URL", f"postgresql://maity:{PASSWORD}@127.0.0.1:1/maity")
    assert main([command]) == 1
    err = capsys.readouterr().err
    assert err.count("\n") == 1
    assert err.startswith("maity-hub: database postgresql+psycopg://maity:***@127.0.0.1:1/maity")
    assert "s3cr" not in err
    assert "Traceback" not in err


def test_an_unwritable_sqlite_path_fails_in_one_line(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("MAITY_DATABASE_URL", "sqlite:////nonexistent/dir/hub.db")
    assert main(["migrate"]) == 1
    err = capsys.readouterr().err
    assert err.count("\n") == 1
    assert "unable to open database file" in err


def test_owner_create_reads_the_password_from_stdin(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import io

    from maity_hub.auth.passwords import verify_password

    assert main(["migrate"]) == 0
    monkeypatch.setattr("sys.stdin", io.StringIO("a long password\n"))
    assert (
        main(
            [
                "owner",
                "create",
                "--handle",
                "maintainer",
                "--display-name",
                "Maint",
                "--email",
                "maintainer@example.org",
            ]
        )
        == 0
    )
    assert "created maintainer (hum-" in capsys.readouterr().out
    from sqlalchemy import create_engine, text

    engine = create_engine("sqlite:///maity-hub.db")
    with engine.connect() as conn:
        stored = conn.execute(text("SELECT password_hash FROM human")).scalar_one()
    engine.dispose()
    assert verify_password("a long password", stored)
    assert "a long password" not in stored

    monkeypatch.setattr("sys.stdin", io.StringIO("another long password\n"))
    assert (
        main(
            [
                "owner",
                "create",
                "--handle",
                "maintainer",
                "--display-name",
                "X",
                "--email",
                "maintainer@example.org",
            ]
        )
        == 1
    )
    assert "exists" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("args", "stdin"),
    [
        (["--handle", "Bad Handle", "--display-name", "X", "--email", "ok@example.org"], "pw\n"),
        (["--handle", "ok", "--display-name", "X", "--email", "ok@example.org"], "\n"),
        (["--handle", "ok", "--display-name", "X", "--email", "ok@example.org"], "eleven char\n"),
    ],
)
def test_owner_create_refuses_a_bad_handle_or_an_empty_password(
    monkeypatch: pytest.MonkeyPatch, args: list[str], stdin: str
) -> None:
    import io

    assert main(["migrate"]) == 0
    monkeypatch.setattr("sys.stdin", io.StringIO(stdin))
    assert main(["owner", "create", *args]) == 2


@pytest.mark.parametrize(("length", "code"), [(31, 0), (32, 2)])
def test_owner_create_takes_a_handle_of_at_most_31_characters(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    length: int,
    code: int,
) -> None:
    """A longer handle names a namespace no project path resolves (namespace.FULL_NAME)."""
    import io

    assert main(["migrate"]) == 0
    monkeypatch.setattr("sys.stdin", io.StringIO(ACCOUNT_PASSWORD + "\n"))
    handle = "a" * length
    args = ["--handle", handle, "--display-name", "X", "--email", "ok@example.org"]
    assert main(["owner", "create", *args]) == code
    if code:
        assert "2 to 31 characters" in capsys.readouterr().err


def test_owner_create_needs_a_migrated_database(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import io

    monkeypatch.setattr("sys.stdin", io.StringIO("a long enough password\n"))
    assert (
        main(
            [
                "owner",
                "create",
                "--handle",
                "ok",
                "--display-name",
                "X",
                "--email",
                "ok@example.org",
            ]
        )
        == 1
    )
    assert "maity-hub migrate" in capsys.readouterr().err


def _banner_only(monkeypatch: pytest.MonkeyPatch) -> None:
    """`run` replaced by what the started server prints: its banner, nothing served."""
    from maity_hub import cli

    monkeypatch.setattr(
        cli._Server, "run", lambda self, sockets=None: print("\n".join(self.banner))
    )


@pytest.mark.parametrize("dashboard", [True, False])
@pytest.mark.wheel
def test_serve_says_where_the_dashboard_is(
    dashboard: bool,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from maity_hub import config

    assert main(["migrate"]) == 0
    capsys.readouterr()
    web = tmp_path / "web"
    if dashboard:
        web.mkdir()
        (web / "index.html").write_text("<!doctype html>")
    monkeypatch.setattr(config, "checkout_web_dir", lambda: web if dashboard else None)
    _banner_only(monkeypatch)
    assert main(["serve"]) == 0
    out = capsys.readouterr().out.strip().splitlines()
    if dashboard:
        assert out[-1] == "maity-hub: dashboard at http://127.0.0.1:8080/"
    else:
        assert out[-1] == "maity-hub: API only at http://127.0.0.1:8080/api/v1, no dashboard"


def test_serve_keeps_idle_connections_longer_than_a_proxy_does(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from maity_hub import cli

    assert main(["migrate"]) == 0
    seen: list[int] = []
    monkeypatch.setattr(
        cli._Server, "run", lambda self, sockets=None: seen.append(self.config.timeout_keep_alive)
    )
    assert main(["serve"]) == 0
    assert seen == [cli.KEEP_ALIVE_SECONDS] and cli.KEEP_ALIVE_SECONDS > 90  # Traefik's pool


def test_serve_runs_on_an_engine_built_from_the_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The pool and the PostgreSQL timeouts of the environment reach the engine the served app
    runs on: `serve` once built its own engine from the URL alone and ignored all of them."""
    from maity_hub import cli
    from tests.test_db_pool import captured_async_connect_args, captured_connect_args

    monkeypatch.setenv("MAITY_DATABASE_URL", "postgresql+psycopg://u:p@localhost/h")
    monkeypatch.setenv("MAITY_DB_POOL_SIZE", "12")
    monkeypatch.setenv("MAITY_DB_MAX_OVERFLOW", "3")
    monkeypatch.setenv("MAITY_DB_POOL_RECYCLE", "60")
    monkeypatch.setenv("MAITY_DB_STATEMENT_TIMEOUT", "11")
    monkeypatch.setenv("MAITY_DB_IDLE_IN_TRANSACTION_TIMEOUT", "22")
    monkeypatch.setattr(cli, "require_current_schema", lambda engine: None)
    monkeypatch.setattr(cli, "warn_on_connection_budget", lambda engine, settings: None)
    served: list[Any] = []
    monkeypatch.setattr(
        cli._Server, "run", lambda self, sockets=None: served.append(self.config.app.state)
    )
    assert main(["serve"]) == 0
    # The pool of 12 split between the engines (`serving.pool_shares`): by default half of it,
    # 6, async without overflow (8 only from a pool of 16), the rest, 6, sync with the whole
    # overflow; the same recycle and timeouts on both.
    engines = (served[0].engine, served[0].async_engine.sync_engine)
    pools: list[Any] = [engine.pool for engine in engines]
    assert [(p.size(), p._max_overflow, p._recycle) for p in pools] == [(6, 3, 60), (6, 0, 60)]
    wanted = (
        "-c TimeZone=UTC -c statement_timeout=11000 -c idle_in_transaction_session_timeout=22000"
    )
    assert captured_connect_args(served[0].engine)["options"] == wanted
    assert captured_async_connect_args(served[0].async_engine)["options"] == wanted


def _stdin(monkeypatch: pytest.MonkeyPatch, text: str) -> None:
    import io

    monkeypatch.setattr("sys.stdin", io.StringIO(text))


def test_quickstart_sets_up_a_new_hub_and_ends_on_the_dashboard(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _banner_only(monkeypatch)
    _stdin(monkeypatch, ACCOUNT_PASSWORD + "\n")
    assert main(["quickstart", "--handle", "me", "--email", "Me@Example.org"]) == 0
    captured = capsys.readouterr()
    out = captured.out.strip().splitlines()
    assert out[0] == f"maity-hub: schema empty -> {head()}"
    assert out[1].startswith("maity-hub: created me (hum-")
    assert out[-2:] == ["maity-hub: sign in as me@example.org", out[-1]]
    assert out[-1].startswith("maity-hub: dashboard at http://127.0.0.1:8080/") or (
        "API only" in out[-1]
    )
    assert ACCOUNT_PASSWORD not in captured.out + captured.err

    _stdin(monkeypatch, "")  # a second start creates nothing and asks for nothing
    assert main(["quickstart"]) == 0
    again = capsys.readouterr().out.strip().splitlines()
    assert again[0] == "maity-hub: this hub has accounts; sign in with yours"
    assert not any("schema" in line or "created" in line for line in again)


def test_quickstart_never_migrates_a_hub_behind_the_schema(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from maity_hub.db import current_revision, downgrade, make_engine

    assert main(["migrate"]) == 0
    engine = make_engine("sqlite:///maity-hub.db")
    downgrade(engine, "0001")
    capsys.readouterr()
    assert main(["quickstart", "--handle", "me"]) == 1
    assert "run `maity-hub migrate` first" in capsys.readouterr().err
    assert current_revision(engine) == "0001"
    engine.dispose()


def test_quickstart_is_for_sqlite_only(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("MAITY_DATABASE_URL", f"postgresql://maity:{PASSWORD}@db/maity")
    assert main(["quickstart"]) == 2
    err = capsys.readouterr().err
    assert "migrate, owner create and serve" in err and PASSWORD not in err


@pytest.mark.parametrize(
    ("login", "handle"),
    [
        ("alice", "alice"),
        ("Bob Smith", "owner"),
        ("admin", "owner"),
        ("a" * 31, "a" * 31),
        ("a" * 32, "owner"),
    ],
)
def test_quickstart_names_the_account_after_the_login(
    login: str,
    handle: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr("getpass.getuser", lambda: login)
    _banner_only(monkeypatch)
    _stdin(monkeypatch, ACCOUNT_PASSWORD + "\n")
    assert main(["quickstart", "--email", "me@example.org"]) == 0
    assert f"maity-hub: created {handle} (hum-" in capsys.readouterr().out


def test_quickstart_never_migrates_a_file_that_holds_tables(
    capsys: pytest.CaptureFixture[str],
) -> None:
    import sqlite3

    with sqlite3.connect("maity-hub.db") as db:
        db.execute("CREATE TABLE notes (text TEXT)")
        db.execute("INSERT INTO notes VALUES ('mine')")
    assert main(["quickstart", "--handle", "me"]) == 1
    assert "holds tables but no Maity schema version" in capsys.readouterr().err
    with sqlite3.connect("maity-hub.db") as db:
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert tables == {"notes"}  # nothing migrated, nothing added


def test_quickstart_never_adds_a_second_first_account(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from maity_hub import cli

    asked = cli._read_password

    def meanwhile() -> str:  # another `owner create` finishes while we ask
        monkeypatch.setattr(cli, "_read_password", asked)
        _stdin(monkeypatch, ACCOUNT_PASSWORD + "\n")
        assert (
            main(
                [
                    "owner",
                    "create",
                    "--handle",
                    "other",
                    "--display-name",
                    "Other",
                    "--email",
                    "other@example.org",
                ]
            )
            == 0
        )
        return ACCOUNT_PASSWORD

    monkeypatch.setattr(cli, "_read_password", meanwhile)
    _banner_only(monkeypatch)
    assert main(["quickstart", "--handle", "me", "--email", "me@example.org"]) == 1
    captured = capsys.readouterr()
    assert "an account was created meanwhile" in captured.err
    assert "sign in as me" not in captured.out
    from maity_hub.db import make_engine

    engine = make_engine("sqlite:///maity-hub.db")
    with engine.connect() as conn:
        from sqlalchemy import select

        from maity_hub import tables as t

        assert [r.handle for r in conn.execute(select(t.human.c.handle))] == ["other"]
    engine.dispose()


def test_owner_create_refuses_a_handle_another_human_kept_as_an_alias(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import io

    from sqlalchemy import create_engine, insert, select

    from maity_hub import clock
    from maity_hub import tables as t

    assert main(["migrate"]) == 0
    monkeypatch.setattr("sys.stdin", io.StringIO("a long password\n"))
    assert (
        main(
            [
                "owner",
                "create",
                "--handle",
                "maintainer",
                "--display-name",
                "Maint",
                "--email",
                "maintainer@example.org",
            ]
        )
        == 0
    )
    engine = create_engine("sqlite:///maity-hub.db")
    with engine.begin() as conn:
        human_id = conn.execute(select(t.human.c.id)).scalar_one()
        conn.execute(
            insert(t.handle_alias).values(
                human_id=human_id, scope="human", handle="old-maint", created_at=clock.now()
            )
        )
    engine.dispose()
    monkeypatch.setattr("sys.stdin", io.StringIO("another long password\n"))
    assert (
        main(
            [
                "owner",
                "create",
                "--handle",
                "old-maint",
                "--display-name",
                "X",
                "--email",
                "old-maint@example.org",
            ]
        )
        == 1
    )
    assert "alias" in capsys.readouterr().err


def test_quickstart_refuses_a_reserved_handle_for_the_first_account(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The first account has no way to be renamed, and `maity-hub migrate` stops on a
    handle that is a first segment of the hub (§16.11): so it is refused up front."""
    _banner_only(monkeypatch)
    _stdin(monkeypatch, ACCOUNT_PASSWORD + "\n")
    assert main(["quickstart", "--handle", "admin", "--email", "me@example.org"]) == 2
    assert "is reserved" in capsys.readouterr().err


def test_owner_create_stores_the_address_as_verified_and_it_signs_in(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """docs/api.md §2.1: the password signs in by the verified address, and the first account
    has it before the instance sends any mail."""
    import io

    from fastapi.testclient import TestClient
    from sqlalchemy import select

    from maity_hub import tables as t
    from maity_hub.app import create_app
    from maity_hub.config import Settings

    assert main(["migrate"]) == 0
    _stdin(monkeypatch, ACCOUNT_PASSWORD + "\n")
    args = ["--handle", "maintainer", "--display-name", "Maint", "--email", " Me@Example.org "]
    assert main(["owner", "create", *args]) == 0
    assert "signing in as me@example.org" in capsys.readouterr().out
    engine = make_engine("sqlite:///maity-hub.db")
    try:
        with engine.connect() as conn:
            row = conn.execute(select(t.notification_settings)).one()
        assert (row.address, row.address_normalized, row.address_status) == (
            "me@example.org",
            "me@example.org",
            "verified",
        )
        monkeypatch.setattr("sys.stdin", io.StringIO(""))
        settings = Settings.from_env({"MAITY_DATABASE_URL": "sqlite:///maity-hub.db"})
        with TestClient(create_app(settings, engine), base_url="https://hub.example") as client:
            body = {"email": "ME@example.org", "password": ACCOUNT_PASSWORD}
            login = client.post("/api/v1/auth/login", json=body)
        assert login.status_code == 200, login.text
    finally:
        engine.dispose()


@pytest.mark.parametrize("email", ["", "me", "a@b", "Me <me@example.org>", "a@example.org,b@x.org"])
def test_owner_create_refuses_anything_but_one_address_before_the_password(
    email: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import io

    assert main(["migrate"]) == 0
    stdin = io.StringIO(ACCOUNT_PASSWORD + "\n")
    monkeypatch.setattr("sys.stdin", stdin)
    args = ["--handle", "maintainer", "--display-name", "Maint", "--email", email]
    assert main(["owner", "create", *args]) == 2
    assert "--email" in capsys.readouterr().err
    assert stdin.tell() == 0  # the password was never asked for


@pytest.mark.parametrize("bad", ["\x85", "\u2028", "\n"])
def test_owner_create_refuses_a_display_name_with_a_line_break(
    bad: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import io

    assert main(["migrate"]) == 0
    stdin = io.StringIO(ACCOUNT_PASSWORD + "\n")
    monkeypatch.setattr("sys.stdin", stdin)
    args = ["--handle", "maintainer", "--display-name", f"Ma{bad}int", "--email", "me@example.org"]
    assert main(["owner", "create", *args]) == 2
    assert "--display-name" in capsys.readouterr().err
    assert stdin.tell() == 0  # the password was never asked for


def test_owner_create_refuses_an_address_another_account_holds(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from sqlalchemy import select

    from maity_hub import tables as t

    assert main(["migrate"]) == 0
    _stdin(monkeypatch, ACCOUNT_PASSWORD + "\n")
    first = ["--handle", "maintainer", "--display-name", "Maint", "--email", "me@example.org"]
    assert main(["owner", "create", *first]) == 0
    _stdin(monkeypatch, ACCOUNT_PASSWORD + "\n")
    second = ["--handle", "other", "--display-name", "Other", "--email", "ME@example.org"]
    assert main(["owner", "create", *second]) == 1
    assert "another account has the address me@example.org" in capsys.readouterr().err
    engine = make_engine("sqlite:///maity-hub.db")
    with engine.connect() as conn:  # the second account rolled back, its handle too
        assert [r.handle for r in conn.execute(select(t.human.c.handle))] == ["maintainer"]
        assert conn.execute(select(t.handle_register.c.handle)).scalars().all() == ["maintainer"]
    engine.dispose()


def test_quickstart_asks_for_the_address_at_a_terminal(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import io

    class Terminal(io.StringIO):
        def isatty(self) -> bool:
            return True

    asked: list[str] = []

    def answer(prompt: str) -> str:
        asked.append(prompt)
        return "me@example.org"

    monkeypatch.setattr("sys.stdin", Terminal(""))
    monkeypatch.setattr("builtins.input", answer)
    monkeypatch.setattr("getpass.getpass", lambda prompt: ACCOUNT_PASSWORD)
    _banner_only(monkeypatch)
    assert main(["quickstart", "--handle", "me"]) == 0
    assert asked == ["email address (you sign in with it): "]
    assert "maity-hub: sign in as me@example.org" in capsys.readouterr().out


def test_quickstart_without_a_terminal_needs_the_address(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from sqlalchemy import select

    from maity_hub import tables as t

    _banner_only(monkeypatch)
    _stdin(monkeypatch, ACCOUNT_PASSWORD + "\n")
    assert main(["quickstart", "--handle", "me"]) == 2
    assert "--email" in capsys.readouterr().err
    engine = make_engine("sqlite:///maity-hub.db")
    with engine.connect() as conn:
        assert conn.execute(select(t.human.c.id)).first() is None
    engine.dispose()
