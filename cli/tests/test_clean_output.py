"""Text from the hub, from GitHub and from the repository reaches the terminal only cleaned.

Every print path below gets the same text with an ESC-led CSI (erase the screen, colour), an
OSC 52 clipboard write and an OSC 0 window title (both ended by BEL), a C1 CSI and a bare BEL;
none of those characters may reach stdout or stderr, and the visible rest of the text must.
"""

from __future__ import annotations

import dataclasses
import io
import json
import os
import urllib.error
from email.message import Message
from pathlib import Path
from typing import Any

import fakehub
import pytest
from conftest import posix

from maity import cli, ghpr, hub, pointer

EVIL = "a\x1b[2J\x1b[31mb\x1b]52;c;aGk=\x07c\x1b]0;title\x07d\x9b31me\x07f"
RAW = ("\x1b", "\x07", "\x9b")


def assert_clean(text: str) -> None:
    assert not [c for c in RAW if c in text], repr(text)


def output(capsys: pytest.CaptureFixture[str]) -> str:
    captured = capsys.readouterr()
    return captured.out + captured.err


# --- hub error code and message -------------------------------------------------------------


def _http_error(body: dict[str, Any], header: str | None = None) -> urllib.error.HTTPError:
    headers = Message()
    if header is not None:
        headers["Maity-Error"] = header
    data = json.dumps(body).encode()
    return urllib.error.HTTPError("https://hub.example", 400, EVIL, headers, io.BytesIO(data))


def test_a_hub_error_shows_its_code_and_message_as_escapes() -> None:
    err = hub._error_from(_http_error({"error": {"code": EVIL, "message": EVIL + "\nnext"}}), "x")
    assert_clean(str(err))
    assert "\n" not in str(err) and "\\x1b]52;c;aGk=\\x07" in str(err)
    assert err.code is not None
    assert_clean(err.code)


def test_a_hub_error_without_a_body_cleans_the_reason_phrase() -> None:
    err = hub._error_from(_http_error({}), "x")
    assert_clean(str(err))
    assert "400 a\\x1b[2J" in str(err)


def test_a_refusal_from_maity_api_reaches_stderr_cleaned(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    error = {"code": "conflict", "message": EVIL, "details": {}}
    fake.routes[("GET", "/api/v1/projects/oliver/maity/x")] = lambda s: (409, {"error": error})
    assert cli.main(["api", "GET", "/projects/oliver/maity/x"]) != cli.EXIT_OK
    out = output(capsys)
    assert_clean(out)
    assert "a\\x1b[2J\\x1b[31mb" in out


# --- other hub text ---------------------------------------------------------------------------


def test_maity_api_prints_a_text_answer_cleaned(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    fake.routes[("GET", "/api/v1/projects/oliver/maity/rules")] = lambda s: (200, EVIL + "\nl2\n")
    assert cli.main(["api", "GET", "/projects/oliver/maity/rules"]) == cli.EXIT_OK
    captured = capsys.readouterr()
    assert_clean(captured.out + captured.err)
    assert captured.out.endswith("f\nl2\n")


def test_maity_help_prints_the_hub_help_cleaned(
    fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    fake.help_text = "# Maity help\n" + EVIL + "\n"
    assert cli.main(["help", "--hub", fake.url]) == cli.EXIT_OK
    captured = capsys.readouterr()
    assert_clean(captured.out + captured.err)
    assert captured.out.startswith("# Maity help\na\\x1b[2J")


def test_join_prints_the_exchange_headers_cleaned(
    clone: Path,
    fake: fakehub.FakeHub,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real = hub.exchange

    def exchange(*args: Any, **kwargs: Any) -> hub.JoinResult:
        result = real(*args, **kwargs)
        return dataclasses.replace(result, project=EVIL, member_id=EVIL, credential_id=EVIL)

    monkeypatch.setattr(hub, "exchange", exchange)
    url = f"{fake.url}/j/{fakehub.TOKEN}"
    assert cli.main(["join", url, "--code", fakehub.CODE, "--no-resume"]) == cli.EXIT_OK
    out = output(capsys)
    assert_clean(out)
    assert "joined a\\x1b[2J" in out


def test_runner_pair_prints_the_exchange_headers_cleaned(
    tmp_path: Path,
    fake: fakehub.FakeHub,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("MAITY_RUNNER_CONFIG", raising=False)
    real = hub.pair_exchange

    def pair(*args: Any, **kwargs: Any) -> hub.PairResult:
        result = real(*args, **kwargs)
        return dataclasses.replace(
            result, runner_id=EVIL, credential_id=EVIL, attached=[EVIL, "sample"]
        )

    monkeypatch.setattr(hub, "pair_exchange", pair)
    url = f"{fake.url}/r/{fakehub.PAIR_TOKEN}"
    assert cli.main(["runner", "pair", url, "--code", fakehub.PAIR_CODE]) == cli.EXIT_OK
    out = output(capsys)
    assert_clean(out)
    assert "paired as runner a\\x1b[2J" in out and "\\x07f, sample" in out


# --- maity gh pr view -------------------------------------------------------------------------


def test_pr_view_text_is_cleaned_field_by_field() -> None:
    pr = {
        "number": 7,
        "title": EVIL + "\nfake line",
        "state": "OPEN",
        "isDraft": False,
        "headRefName": EVIL,
        "baseRefName": "main",
        "url": EVIL,
        "author": {"login": EVIL},
        "body": EVIL + "\nsecond",
        "comments": [{"author": {"login": EVIL}, "createdAt": EVIL, "body": EVIL}],
    }
    text = ghpr._readable(json.dumps(pr).encode())
    assert_clean(text)
    lines = text.split("\n")
    assert lines[0].startswith("#7 a\\x1b[2J") and lines[0].endswith("\\nfake line")
    assert "second" in lines


def test_pr_view_raw_fallback_is_cleaned() -> None:
    text = ghpr._readable(("not json " + EVIL).encode())
    assert_clean(text)
    assert text.startswith("not json a\\x1b[2J")


# --- join --pointer ---------------------------------------------------------------------------


@posix
@pytest.mark.parametrize("name", ["AGENTS.md", "CLAUDE.md"])
def test_pointer_refuses_a_link_to_a_file_outside_the_repository(tmp_path: Path, name: str) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("keep me\n")
    (root / name).symlink_to(outside)
    changed, refused = pointer.write(root)
    assert outside.read_text() == "keep me\n"
    assert len(refused) == 1 and "symbolic link" in refused[0] and name in refused[0]
    assert (root / name) not in changed
    if name == "CLAUDE.md":  # AGENTS.md is a plain file and still gets the block
        assert changed == [root / "AGENTS.md"]


@posix
def test_pointer_refuses_a_dangling_link(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    target = tmp_path / "created-outside"
    (root / "AGENTS.md").symlink_to(target)
    changed, refused = pointer.write(root)
    assert changed == [] and len(refused) == 1
    assert not target.exists()


@posix
def test_pointer_accepts_claude_md_linked_to_this_agents_md(tmp_path: Path) -> None:
    (tmp_path / "CLAUDE.md").symlink_to("AGENTS.md")
    changed, refused = pointer.write(tmp_path)
    assert changed == [tmp_path / "AGENTS.md"] and refused == []
    assert pointer.BEGIN in (tmp_path / "CLAUDE.md").read_text()


@posix
def test_join_pointer_with_a_linked_agents_md_writes_nothing_and_prints_the_block(
    clone: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    outside = tmp_path / "outside.txt"
    outside.write_text("keep me\n")
    (clone / "AGENTS.md").symlink_to(outside)
    url = f"{fake.url}/j/{fakehub.TOKEN}"
    code = cli.main(["join", url, "--code", fakehub.CODE, "--no-resume", "--pointer"])
    err = capsys.readouterr().err
    assert code == cli.EXIT_OK, err
    assert outside.read_text() == "keep me\n"
    assert "not written" in err and "symbolic link" in err
    assert pointer.BLOCK in err
    assert os.path.islink(clone / "AGENTS.md")


# --- attachment ids in say's status lines -----------------------------------------------------

P = "/api/v1/projects/oliver/maity"


def _upload_answers_evil(fake: fakehub.FakeHub) -> None:
    fake.routes[("POST", f"{P}/attachments")] = lambda s: (201, {"id": EVIL, "name": "a.txt"})


def test_a_kept_upload_after_a_5xx_is_named_cleaned(
    joined: Path, fake: fakehub.FakeHub, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "a.txt").write_bytes(b"x")
    _upload_answers_evil(fake)
    fake.routes[("POST", f"{P}/events")] = lambda s: (
        504, {"error": {"code": "gateway", "message": "g", "details": {}}})  # fmt: skip
    argv = ["say", "all", "x", "--type", "notice", "--attach", str(tmp_path / "a.txt")]
    assert cli.main(argv) == cli.EXIT_ERROR
    out = output(capsys)
    assert_clean(out)
    assert "its attachments: a\\x1b[2J" in out


def test_an_upload_still_pending_after_a_refusal_is_named_cleaned(
    joined: Path, fake: fakehub.FakeHub, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "a.txt").write_bytes(b"x")
    _upload_answers_evil(fake)
    fake.routes[("POST", f"{P}/events")] = lambda s: (
        422, {"error": {"code": "invalid", "message": "i", "details": {}}})  # fmt: skip
    # no DELETE route for that id: the fake hub answers 404, so the upload stays pending
    argv = ["say", "all", "x", "--type", "notice", "--attach", str(tmp_path / "a.txt")]
    assert cli.main(argv) == cli.EXIT_ERROR
    out = output(capsys)
    assert_clean(out)
    assert "still pending (they expire after 24 hours): a\\x1b[2J" in out


def test_a_post_that_fails_otherwise_names_its_uploads_cleaned(
    joined: Path, fake: fakehub.FakeHub, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "a.txt").write_bytes(b"x")
    _upload_answers_evil(fake)

    def post(ids: list[str]) -> Any:
        raise RuntimeError("connection dropped")

    with pytest.raises(RuntimeError):
        cli._post_with(cli.Session(), [str(tmp_path / "a.txt")], post)
    out = output(capsys)
    assert_clean(out)
    assert "its attachments: a\\x1b[2J" in out


# --- join --pointer: the directory and errors -------------------------------------------------


@posix
@pytest.mark.skipif(not pointer._DIR_FD, reason="opens relative to a directory only on POSIX")
def test_pointer_writes_into_the_directory_it_opened_when_the_root_is_swapped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, moved, outside = tmp_path / "repo", tmp_path / "repo-moved", tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (outside / "AGENTS.md").write_text("keep me\n")
    real = pointer._Root

    def swapped(path: Path) -> pointer._Root:
        opened = real(path)
        root.rename(moved)  # after the root is opened, before any file in it is
        root.symlink_to(outside)
        return opened

    monkeypatch.setattr(pointer, "_Root", swapped)
    changed, refused = pointer.write(root)
    assert refused == [] and changed == [root / "AGENTS.md"]
    assert (outside / "AGENTS.md").read_text() == "keep me\n"
    assert pointer.BEGIN in (moved / "AGENTS.md").read_text()


@posix
def test_pointer_turns_an_error_opening_the_file_into_a_refusal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "CLAUDE.md").write_text("# own rules\n")

    def fails(self: pointer._Root, name: str, flags: int) -> int:
        raise OSError(40, "Too many levels of symbolic links")

    monkeypatch.setattr(pointer._Root, "open", fails)
    changed, refused = pointer.write(tmp_path)
    assert changed == [] and len(refused) == 2
    assert all("could not be written (Too many levels of symbolic links)" in r for r in refused)


@posix
def test_join_pointer_prints_the_block_when_opening_the_file_fails(
    clone: Path,
    fake: fakehub.FakeHub,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fails(self: pointer._Root, name: str, flags: int) -> int:
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(pointer._Root, "open", fails)
    url = f"{fake.url}/j/{fakehub.TOKEN}"
    code = cli.main(["join", url, "--code", fakehub.CODE, "--no-resume", "--pointer"])
    err = capsys.readouterr().err
    assert code == cli.EXIT_OK, err
    assert "not written" in err and "Permission denied" in err and pointer.BLOCK in err


@posix
def test_pointer_refuses_a_fifo_without_waiting(tmp_path: Path) -> None:
    os.mkfifo(tmp_path / "AGENTS.md")
    changed, refused = pointer.write(tmp_path)
    assert changed == [] and refused == [f"{tmp_path / 'AGENTS.md'} is not a regular file"]
