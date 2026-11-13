"""Every file an agent names for maity to read, under a runner placement: only a regular file in
the clone, outside its `.git`, not through a link and not one with another hard link
(inclone.read, cli/context/runner.md). Outside a placement each reads as before."""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from pathlib import Path

import fakehub
import pytest
from conftest import posix

from maity import cli, clonecheck, inclone

P = "/api/v1/projects/oliver/maity"
SECRET = b"SECRET-OUTSIDE-THE-CLONE"
# A body each command would take, with the marker in it, so a read that was not confined
# would carry it on to the hub.
CONTENT = json.dumps({"went_well": SECRET.decode(), "topics": []}).encode()
PNG = b"\x89PNG\r\n\x1a\n" + SECRET

# Each read flag, as a command line around the path; the stdin form where the flag has one.
COMMANDS: dict[str, Callable[[str], list[str]]] = {
    "files put": lambda p: ["files", "put", p],
    "--attach": lambda p: ["say", "--attach", p, "human", "hi"],
    "--body-file": lambda p: ["say", "--type", "notice", "--body-file", p, "agt-c"],
    "ask --body-file": lambda p: ["ask", "--to", "owner", "--class", "info", "--body-file", p],
    "--summary-file": lambda p: ["report", "--task", "tsk-0001", "--summary-file", p],
    "--last-file": lambda p: ["checkpoint", "tsk-0001", "--last-file", p, "--next", "n"],
    "--next-file": lambda p: ["checkpoint", "tsk-0001", "-m", "m", "--next-file", p],
    "--review-file": lambda p: ["say", "--type", "review_result", "--review-file", p, "agt-c",
                                "text"],  # fmt: skip
    "api --json": lambda p: ["api", "POST", "/projects/oliver/maity/tasks", "--json", p],
    "--action-body": lambda p: ["ask", "--to", "owner", "--class", "decision", "--action",
                                "PATCH /projects/oliver/maity/members/agt-c", "--action-body",
                                p, "go?"],  # fmt: skip
    "jourfixe statement --file": lambda p: ["jourfixe", "statement", "jfr-1", "--file", p],
    "jourfixe report --file": lambda p: ["jourfixe", "report", "jfr-1", "--file", p],
    "jourfixe answer --file": lambda p: ["jourfixe", "answer", "--file", p],
    "profile avatar": lambda p: ["profile", "avatar", p],
    "memory add --soul": lambda p: ["memory", "add", "--soul", p, "--reason", "r"],
    "task restricted set --file": lambda p: ["task", "restricted", "set", "tsk-0001",
                                             "--file", p],  # fmt: skip
    "join --join-file": lambda p: ["join", "--join-file", p],
}
walks = pytest.mark.skipif(not inclone.WALKS, reason="no dir_fd or O_NOFOLLOW: refused here")


@pytest.fixture
def placed(
    joined: Path, fake: fakehub.FakeHub, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Path:
    """The joined clone (the working directory) under a placement, with the variables the
    runner sets for a session."""
    clone = Path.cwd()
    monkeypatch.setenv(clonecheck.PLACEMENT_ENV, "plc-0003")
    monkeypatch.setenv("GIT_COMMON_DIR", str(clone / ".git"))
    monkeypatch.setenv(clonecheck.GIT_INODE_ENV, str(os.lstat(clone / ".git").st_ino))
    private = tmp_path / "agent" / "git"
    private.mkdir(parents=True)
    monkeypatch.setenv(clonecheck.GIT_PRIVATE_ENV, str(private))
    return clone


def secret(tmp_path: Path, name: str = "secret.txt") -> Path:
    """A file outside the clone, with the marker."""
    outside = tmp_path / "outside"
    outside.mkdir(exist_ok=True)
    path = outside / name
    path.write_bytes(PNG if name.endswith(".png") else CONTENT)
    return path


def refused_paths(clone: Path, tmp_path: Path) -> dict[str, tuple[str, str]]:
    """Each way out of the clone, as the path given and the refusal's reason."""
    target = secret(tmp_path)
    (clone / "via-link").symlink_to(target)
    os.link(target, clone / "via-hard-link")
    inner = clone / ".git" / "maity"
    inner.mkdir(exist_ok=True)
    (inner / "secret.txt").write_bytes(CONTENT)
    return {
        "absolute": (str(target), "not a file in this clone"),
        "parent": (os.path.join("..", "outside", "secret.txt"), "not a file in this clone"),
        "git": (os.path.join(".git", "maity", "secret.txt"), "under the clone's .git"),
        "symlink": ("via-link", "a link"),
        "hard link": ("via-hard-link", "other hard links"),
    }


def leaked(fake: fakehub.FakeHub) -> bool:
    return any(SECRET in seen.body or SECRET in seen.query.encode() for seen in fake.seen)


@posix
@walks
@pytest.mark.parametrize("command", sorted(COMMANDS))
def test_every_read_flag_refuses_every_way_out_of_the_clone(
    placed: Path,
    fake: fakehub.FakeHub,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    command: str,
) -> None:
    for way, (given, reason) in refused_paths(placed, tmp_path).items():
        assert cli.main(COMMANDS[command](given)) == cli.EXIT_USAGE, (command, way)
        err = capsys.readouterr().err
        restricted = command == "task restricted set --file"
        assert (cli.QUIET_REFUSAL if restricted else reason) in err, (command, way, err)
        assert not leaked(fake), (command, way)
        if restricted:  # a text given there by mistake stays unsaid
            assert given not in err and os.path.basename(given) not in err


@posix
@walks
def test_a_file_in_the_clone_is_read_and_sent(
    placed: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    fake.routes[("POST", f"{P}/tasks")] = lambda s: (201, {"id": "tsk-0009", **s.json()})
    (placed / "work").mkdir()
    (placed / "work" / "body.json").write_bytes(b'{"title": "from the clone"}')
    assert cli.main(["api", "POST", "/projects/oliver/maity/tasks", "--json",
                     "work/body.json"]) == cli.EXIT_OK  # fmt: skip
    assert fake.seen[-1].json() == {"title": "from the clone"}
    capsys.readouterr()
    body = placed / "note.md"
    body.write_bytes(b"\xef\xbb\xbfline one\r\nline two\n")
    assert cli._read_text_file(str(body), "--body-file") == "line one\nline two\n"


@posix
@walks
def test_stdin_stays_where_a_flag_takes_it(
    placed: Path, fake: fakehub.FakeHub, monkeypatch: pytest.MonkeyPatch
) -> None:
    import io
    import sys

    fake.routes[("POST", f"{P}/tasks")] = lambda s: (201, {"id": "tsk-0009", **s.json()})
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(b'{"title": "piped"}')))
    assert cli.main(["api", "POST", "/projects/oliver/maity/tasks", "--json", "-"]) == 0
    assert fake.seen[-1].json() == {"title": "piped"}


@posix
@walks
def test_a_directory_or_a_fifo_is_not_a_file(
    placed: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (placed / "folder").mkdir()
    os.mkfifo(placed / "pipe")
    for given in ("folder", "pipe"):
        assert cli.main(["files", "put", given]) == cli.EXIT_USAGE
        assert "not a plain file" in capsys.readouterr().err


def test_without_descriptors_maity_reads_no_named_file(
    placed: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(inclone, "WALKS", False)
    (placed / "body.json").write_bytes(b"{}")
    assert cli.main(["api", "POST", "/projects/oliver/maity/tasks", "--json", "body.json"]) == 2
    assert "cannot open a file without following links" in capsys.readouterr().err


def test_a_session_without_the_runners_git_inode_reads_nothing(
    placed: Path, fake: fakehub.FakeHub, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(clonecheck.GIT_INODE_ENV)
    (placed / "body.json").write_bytes(b"{}")
    assert cli.main(["api", "POST", "/projects/oliver/maity/tasks", "--json", "body.json"]) == 2
    assert not [s for s in fake.seen if s.method == "POST"]


@posix
def test_outside_a_placement_every_path_is_read_as_before(
    joined: Path, fake: fakehub.FakeHub, tmp_path: Path
) -> None:
    target = secret(tmp_path)
    clone = Path.cwd()
    (clone / "via-link").symlink_to(target)
    os.link(target, clone / "via-hard-link")
    for given in (str(target), os.path.join("..", "outside", "secret.txt"), "via-link",
                  "via-hard-link"):  # fmt: skip
        assert cli._read_bytes(given, "--json") == CONTENT
        assert cli._read_text_file(given, "--body-file") == CONTENT.decode()
        assert cli._read_upload(given) == CONTENT
        assert cli._restricted_text(given) == CONTENT.decode()
    fake.routes[("POST", f"{P}/tasks")] = lambda s: (201, {"id": "tsk-0009", **s.json()})
    assert cli.main(["api", "POST", "/projects/oliver/maity/tasks", "--json", str(target)]) == 0
    assert leaked(fake)  # unchanged: no placement, no confinement
