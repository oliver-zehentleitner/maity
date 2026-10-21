from __future__ import annotations

from pathlib import Path

import pytest

from maity_hub.cli import main

PASSWORD = "s3cret-pw"


@pytest.fixture(autouse=True)
def isolated_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    for name in ("MAITY_DATABASE_URL", "MAITY_BIND", "MAITY_PUBLIC_URL", "MAITY_WEB_DIR"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)


def test_migrate_then_report(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["migrate"]) == 0
    assert "schema empty -> 0001" in capsys.readouterr().out
    assert Path("maity-hub.db").is_file()


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


def test_an_unencoded_at_in_the_password_is_refused_without_echo(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("MAITY_DATABASE_URL", "postgresql://maity:s3cr@t-pw@db/maity")
    assert main(["migrate"]) == 2
    err = capsys.readouterr().err
    assert "percent-encoded" in err
    assert "s3cr" not in err
    assert "t-pw" not in err


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
