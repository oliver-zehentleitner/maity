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
from maity.runner import scratchop, workspace

makes_tmp = pytest.mark.skipif(
    not scratchop.supported(), reason="no descriptor-relative scratch here"
)

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


# --- the placement's scratch (§15.5) ---------------------------------------------------------


def scratch_recorded(tmp_path: Path, record: str | None = None) -> Path:
    """A scratch beside the clone, named in the runner's record as the runner writes it."""
    room = tmp_path / "ws" / "maity" / ".scratch" / "plc-0003"
    room.mkdir(parents=True)
    private = Path(os.environ[clonecheck.GIT_PRIVATE_ENV])
    text = f"{room}\n" if record is None else record
    (private / clonecheck.SCRATCH_RECORD).write_text(text)
    return room


@posix
@walks
def test_a_file_in_the_recorded_scratch_is_read_and_sent(
    placed: Path, fake: fakehub.FakeHub, tmp_path: Path
) -> None:
    fake.routes[("POST", f"{P}/tasks")] = lambda s: (201, {"id": "tsk-0009", **s.json()})
    room = scratch_recorded(tmp_path)
    (room / "evidence").mkdir()
    (room / "evidence" / "body.json").write_bytes(b'{"title": "from the scratch"}')
    given = str(room / "evidence" / "body.json")
    assert cli.main(["api", "POST", "/projects/oliver/maity/tasks", "--json", given]) == 0
    assert fake.seen[-1].json() == {"title": "from the scratch"}


@posix
@walks
@pytest.mark.parametrize("layout", ["runner-dir", "codex"])
def test_a_body_file_in_a_scratch_subdirectory_beside_tmpdir_is_read(
    placed: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, layout: str
) -> None:
    """tsk-x6wvgna4w95x: a file in `<scratch>/sub/`, a sibling of the session's TMPDIR
    (`<scratch>/tmp`), is read for `--body-file`, `--review-file` and `--attach` like one under
    TMPDIR: the whole recorded scratch counts, not TMPDIR alone. Also with the record where a
    Codex placement keeps it, the clone's `.git/maity` (IN_CLONE)."""
    room = tmp_path / "ws" / "maity" / ".scratch" / "plc-0003"
    (room / "tmp").mkdir(parents=True)
    (room / "sub").mkdir()
    monkeypatch.setenv("TMPDIR", str(room / "tmp"))
    if layout == "codex":
        monkeypatch.setenv(clonecheck.GIT_PRIVATE_ENV, clonecheck.IN_CLONE)
        private = placed / ".git" / "maity"
        private.mkdir(exist_ok=True)
    else:
        private = Path(os.environ[clonecheck.GIT_PRIVATE_ENV])
    (private / clonecheck.SCRATCH_RECORD).write_text(f"{room}\n")
    (room / "sub" / "body.md").write_bytes(b"from a scratch subdirectory\n")
    (room / "tmp" / "body.md").write_bytes(b"from TMPDIR\n")
    for flag in ("--body-file", "--review-file"):
        assert cli._read_text_file(str(room / "sub" / "body.md"), flag) == (
            "from a scratch subdirectory\n"
        )
        assert cli._read_text_file(str(room / "tmp" / "body.md"), flag) == "from TMPDIR\n"
    assert cli._read_upload(str(room / "sub" / "body.md"), "--attach") == (
        b"from a scratch subdirectory\n"
    )
    # Relative to a working directory inside the scratch, as `cd $MAITY_SCRATCH` leaves it.
    monkeypatch.chdir(room / "sub")
    assert cli._read_text_file("body.md", "--body-file") == "from a scratch subdirectory\n"


# Codex's profile hides the workspaces root and the scratch's holder from reading ("none") and
# opens the scratch again: a path passes through them, a directory open for reading does not.
# A search-only directory (0o111) is the closest stand-in outside bwrap; root reads it anyway.
hides_from_reading = pytest.mark.skipif(
    not hasattr(os, "O_PATH") or (hasattr(os, "geteuid") and os.geteuid() == 0),
    reason="needs O_PATH, and a user a search-only directory keeps from reading",
)


@posix
@walks
@hides_from_reading
@pytest.mark.parametrize("hidden", ["workspaces", "holder", "both"])
def test_a_scratch_whose_parents_cannot_be_read_is_still_read(
    placed: Path, tmp_path: Path, hidden: str
) -> None:
    """tsk-x6wvgna4w95x, tsk-vt5hye6a6k6v: under Codex every file in the scratch was refused
    ("the way to the placement's scratch (…) is not plain directories"; live probe A1718 on
    maity 0.1.0a17), because the walk from `/` opened each parent for reading. Red on
    530b070e. Now each parent is only passed through, as the agent's own shell does."""
    room = scratch_recorded(tmp_path)
    (room / "sub").mkdir()
    (room / "sub" / "body.md").write_bytes(b"behind a parent nobody may read\n")
    workspaces, holder = room.parent.parent.parent, room.parent
    shut = {"workspaces": [workspaces], "holder": [holder], "both": [workspaces, holder]}[hidden]
    for directory in shut:
        directory.chmod(0o111)
    try:
        given = str(room / "sub" / "body.md")
        for flag in ("--body-file", "--review-file"):
            assert cli._read_text_file(given, flag) == "behind a parent nobody may read\n"
        assert cli._read_upload(given, "--attach") == b"behind a parent nobody may read\n"
    finally:
        for directory in shut:
            directory.chmod(0o755)


@posix
@walks
@hides_from_reading
def test_a_link_on_the_way_is_refused_behind_a_parent_that_cannot_be_read(
    placed: Path, tmp_path: Path
) -> None:
    """Passing a parent through instead of reading it keeps the walk's boundary: a link on
    the way to the scratch is still refused, also below a search-only directory."""
    real = tmp_path / "elsewhere" / ".scratch" / "plc-0003"
    real.mkdir(parents=True)
    (real / "body.json").write_bytes(CONTENT)
    workspaces = tmp_path / "ws"
    workspaces.mkdir()
    (workspaces / "maity").symlink_to(tmp_path / "elsewhere")
    room = workspaces / "maity" / ".scratch" / "plc-0003"
    private = Path(os.environ[clonecheck.GIT_PRIVATE_ENV])
    (private / clonecheck.SCRATCH_RECORD).write_text(f"{room}\n")
    workspaces.chmod(0o111)
    try:
        with pytest.raises(cli.UsageError, match="not plain directories"):
            cli._read_text_file(str(room / "body.json"), "--body-file")
    finally:
        workspaces.chmod(0o755)


@posix
@walks
@pytest.mark.parametrize("way", ["beside", "link", "linked-scratch", "linked-holder",
                                 "linked-project", "linked-workspaces", "no-record",
                                 "empty-record", "record-in-clone"])  # fmt: skip
def test_only_the_recorded_scratch_is_read_and_never_through_a_link(
    placed: Path, fake: fakehub.FakeHub, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    way: str,
) -> None:  # fmt: skip
    record = {"no-record": None, "empty-record": "", "record-in-clone": f"{placed}/sub\n"}
    if way in ("no-record", "empty-record", "record-in-clone"):
        room = tmp_path / "ws" / "maity" / ".scratch" / "plc-0003"
        room.mkdir(parents=True)
        if way != "no-record":
            private = Path(os.environ[clonecheck.GIT_PRIVATE_ENV])
            (private / clonecheck.SCRATCH_RECORD).write_text(str(record[way]))
        given = room / "body.json"
        given.write_bytes(CONTENT)
    elif way in ("linked-scratch", "linked-holder", "linked-project", "linked-workspaces"):
        # The record names the right path; one directory on the way to it is a link the
        # agents could have made after the runner wrote the record.
        real = tmp_path / "elsewhere"
        room = tmp_path / "ws" / "maity" / ".scratch" / "plc-0003"
        linked = {"linked-scratch": room, "linked-holder": room.parent,
                  "linked-project": room.parent.parent,
                  "linked-workspaces": room.parent.parent.parent}[way]  # fmt: skip
        below = room.relative_to(linked)
        (real / below).mkdir(parents=True)
        (real / below / "body.json").write_bytes(CONTENT)
        linked.parent.mkdir(parents=True, exist_ok=True)
        linked.symlink_to(real)
        private = Path(os.environ[clonecheck.GIT_PRIVATE_ENV])
        (private / clonecheck.SCRATCH_RECORD).write_text(f"{room}\n")
        given = room / "body.json"
    else:
        room = scratch_recorded(tmp_path)
        target = secret(tmp_path)
        if way == "link":
            (room / "via-link").symlink_to(target)
            given = room / "via-link"
        else:  # a directory beside the scratch, not in it
            given = target
    assert cli.main(["api", "POST", "/projects/oliver/maity/tasks", "--json", str(given)]) == 2
    err = capsys.readouterr().err
    assert not leaked(fake), (way, err)
    plain = "not plain directories"
    reason = {"link": "a link", "linked-scratch": plain, "linked-holder": plain,
              "linked-project": plain, "linked-workspaces": plain}.get(
        way, "not a file in this clone"
    )  # fmt: skip
    assert reason in err, (way, err)


@posix
@walks
def test_a_review_file_under_the_agy_scratch_is_accepted_and_one_outside_is_refused(
    placed: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """An agy reviewer's scratch is recorded under `/tmp` (maity-scratch-<uid>/<placement>),
    not beside the clone; `--review-file $MAITY_SCRATCH/review.json` is read through the same
    inclone path as any recorded scratch, and a path outside it is still refused."""
    room = tmp_path / f"maity-scratch-{os.getuid()}" / "plc-0003"
    room.mkdir(parents=True)
    private = Path(os.environ[clonecheck.GIT_PRIVATE_ENV])
    (private / clonecheck.SCRATCH_RECORD).write_text(f"{room}\n")
    (room / "review.json").write_bytes(b'{"verdict": "approve"}')
    accepted = cli._read_text_file(str(room / "review.json"), "--review-file")
    assert accepted == '{"verdict": "approve"}'
    outside = secret(tmp_path)  # a file beside the scratch, not in it (nor in the clone)
    with pytest.raises(cli.UsageError, match="not a file in this clone"):
        cli._read_text_file(str(outside), "--review-file")
    assert SECRET not in capsys.readouterr().out.encode()  # nothing of it was read out


def test_the_changelog_states_the_agy_scratch_residual_honestly() -> None:
    """The residual wording does not overclaim same-user isolation (review round 3): the agy
    scratch is not said to be reachable only by the owning placement, and the accepted same-user
    exposure is named. Red on dc826d9b, whose changelog claimed an unlistable parent and an
    unguessable name only the owning placement could reach. The agy writable-scratch fragment
    was folded into CHANGELOG.md's 0.1.0a10 release section, so the assertions read that section."""
    changelog = Path(__file__).resolve().parents[2] / "CHANGELOG.md"
    lines = changelog.read_text(encoding="utf-8").splitlines(keepends=True)
    start = next(i for i, ln in enumerate(lines) if ln.startswith("## [0.1.0a10]"))
    end = next(
        (i for i in range(start + 1, len(lines)) if lines[i].startswith("## [")),
        len(lines),
    )
    text = "".join(lines[start:end])
    assert "only the owning placement" not in text
    assert "unlistable" not in text and "unguessable" not in text
    assert "same host user" in text  # the accepted residual is stated


@posix
@walks
@makes_tmp
def test_a_review_file_in_a_production_made_agy_scratch_is_read(
    placed: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """End-to-end on the real layout: the agy scratch is created exactly as production does
    (scratchop.tmp_make — a 0700 per-user parent and a random leaf), then the review file is
    read through the real recorded-scratch path. Red on dc826d9b, where the per-user parent was
    made 0300 (unreadable): maity's read walks it O_RDONLY from `/`, so the parent blocked every
    `--review-file`/`--body-file` read of an agy placement. The round-2 tests missed this
    because they created the parent 0755 by hand rather than through tmp_make."""
    shared = tmp_path / "shared-tmp"
    shared.mkdir()
    monkeypatch.setattr(workspace, "TMP_SCRATCH_ROOT", shared)
    leaf = "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
    room = workspace.tmp_scratch_of(os.getuid(), leaf)
    scratchop.tmp_make(str(room))  # exactly as the runner makes it: 0700 parent, 0700 leaf
    (room / "review.json").write_bytes(b'{"verdict": "approve"}')
    private = Path(os.environ[clonecheck.GIT_PRIVATE_ENV])
    (private / clonecheck.SCRATCH_RECORD).write_text(f"{room}\n")
    assert cli._read_text_file(str(room / "review.json"), "--review-file") == (
        '{"verdict": "approve"}'
    )


@posix
@walks
def test_the_agy_scratch_root_is_resolved_so_a_symlinked_temp_dir_still_reads(
    placed: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The shared temp directory is a link on some hosts (macOS `/tmp` -> `/private/tmp`).
    tmp_scratch_of resolves the root, so the recorded scratch path has no link on the way and
    the session's own `--review-file` read (which walks it from `/` refusing any link) works;
    the unresolved spelling, through the link, is refused — which is why resolving matters."""
    from maity.runner import workspace

    real, link = tmp_path / "real-tmp", tmp_path / "linked-tmp"
    real.mkdir()
    link.symlink_to(real)
    monkeypatch.setattr(workspace, "TMP_SCRATCH_ROOT", link)
    leaf = "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
    recorded = workspace.tmp_scratch_of(os.getuid(), leaf)
    assert link not in recorded.parents and real in recorded.parents  # resolved, no link
    recorded.mkdir(parents=True)
    private = Path(os.environ[clonecheck.GIT_PRIVATE_ENV])
    (private / clonecheck.SCRATCH_RECORD).write_text(f"{recorded}\n")
    (recorded / "review.json").write_bytes(b'{"verdict": "approve"}')
    assert cli._read_text_file(str(recorded / "review.json"), "--review-file") == (
        '{"verdict": "approve"}'
    )
    # Had the runner recorded the unresolved (symlinked) spelling, the read would be refused.
    through_link = link / f"maity-scratch-{os.getuid()}" / leaf
    (private / clonecheck.SCRATCH_RECORD).write_text(f"{through_link}\n")
    with pytest.raises(cli.UsageError):
        cli._read_text_file(str(through_link / "review.json"), "--review-file")
