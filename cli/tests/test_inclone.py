"""`maity files get` under a runner placement: only into the clone, outside its `.git`, never
through a link and never over an existing file (inclone, cli/context/runner.md). Outside a
placement it behaves as before (test_chats_files.py)."""

from __future__ import annotations

import contextlib
import errno
import hashlib
import os
import stat
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import fakehub
import pytest
from conftest import posix

from maity import cli, clonecheck, inclone

P = "/api/v1/projects/oliver/maity"
walks = pytest.mark.skipif(not inclone.WALKS, reason="no dir_fd or O_NOFOLLOW: refused here")


def attachment(**extra: Any) -> dict[str, Any]:
    return {"id": "att-0042", "name": "build-log.txt", "size": 5, "type": "text/plain",
            "kind": "file", "sha256": hashlib.sha256(b"hello").hexdigest(), "width": None,
            "height": None, "uploaded_by": "agt-b", "message_seq": None, "deleted_at": None,
            **extra}  # fmt: skip


@pytest.fixture
def served(fake: fakehub.FakeHub) -> fakehub.FakeHub:
    fake.routes[("GET", f"{P}/attachments/att-0042")] = lambda s: (200, attachment())
    fake.routes[("GET", f"{P}/attachments/att-0042/content")] = lambda s: (200, b"hello")
    return fake


@pytest.fixture
def placed(
    joined: Path, served: fakehub.FakeHub, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
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


def get(*extra: str) -> int:
    return cli.main(["files", "get", "att-0042", *extra])


def parts(directory: Path) -> list[Path]:
    return [p for p in directory.rglob("*") if p.name.endswith(".part")]


@posix
@walks
def test_the_default_lands_in_maity_files_in_the_clone(placed: Path) -> None:
    old = os.umask(0o022)
    try:
        assert get() == cli.EXIT_OK
    finally:
        os.umask(old)
    saved = placed / "maity-files" / "build-log.txt"
    assert saved.read_bytes() == b"hello"
    assert stat.S_IMODE(saved.stat().st_mode) == 0o644
    assert stat.S_IMODE(saved.parent.stat().st_mode) == 0o700
    assert parts(placed) == []


@walks
def test_a_path_inside_the_clone_is_written(placed: Path) -> None:
    (placed / "docs").mkdir()
    assert get("-o", "docs/log.txt") == cli.EXIT_OK
    assert (placed / "docs" / "log.txt").read_bytes() == b"hello"
    os.chdir(placed / "docs")  # relative to the working directory, as the agent wrote it
    assert get("-o", "../again.txt") == cli.EXIT_OK
    assert (placed / "again.txt").read_bytes() == b"hello"


@walks
@pytest.mark.parametrize(
    "target", [".git/maity/git", ".git/maity/pull_requests", ".git/config", ".git/new", ".git"]
)
@pytest.mark.parametrize("force", [[], ["--force"]])
def test_a_path_into_git_is_refused(
    placed: Path, target: str, force: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    before = {p: p.read_bytes() for p in (placed / ".git").rglob("*") if p.is_file()}
    assert get("-o", target, *force) == cli.EXIT_ERROR
    err = capsys.readouterr().err
    assert ".git" in err and "saved" not in err
    after = {p: p.read_bytes() for p in (placed / ".git").rglob("*") if p.is_file()}
    assert after == before


@walks
def test_a_case_variant_of_git_is_refused_where_the_volume_folds_case(placed: Path) -> None:
    if not (placed / ".GIT").exists():
        pytest.skip("a case-sensitive file system: .GIT is another directory")
    assert get("-o", ".GIT/new") == cli.EXIT_ERROR
    assert not (placed / ".git" / "new").exists()


@walks
def test_a_path_outside_the_clone_is_refused(
    placed: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    runners = tmp_path / "agent" / "git" / "git"
    for target in (str(home / ".profile"), "../outside.txt", str(runners)):
        assert get("-o", target, "--force") == cli.EXIT_ERROR
        assert "not a file in this clone" in capsys.readouterr().err
    assert not (home / ".profile").exists() and not (placed.parent / "outside.txt").exists()
    assert not runners.exists()


@posix
@walks
def test_a_link_on_the_way_or_at_the_name_is_refused(
    placed: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (placed / "g").symlink_to(".git", target_is_directory=True)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (placed / "out").symlink_to(elsewhere, target_is_directory=True)
    victim = tmp_path / "victim"
    victim.write_bytes(b"keep")
    (placed / "leaf.txt").symlink_to(victim)
    for target in ("g/maity/git", "g/config", "out/x.txt"):
        assert get("-o", target, "--force") == cli.EXIT_ERROR
        assert "a link; name the file itself" in capsys.readouterr().err
    assert get("-o", "leaf.txt", "--force") == cli.EXIT_ERROR
    assert "exists" in capsys.readouterr().err
    assert not (placed / ".git" / "maity" / "git").exists()
    assert list(elsewhere.iterdir()) == [] and victim.read_bytes() == b"keep"


@posix
@walks
def test_maity_files_as_a_link_is_refused(placed: Path, tmp_path: Path) -> None:
    (placed / "maity-files").symlink_to(placed / ".git", target_is_directory=True)
    assert get() == cli.EXIT_ERROR
    assert not (placed / ".git" / "build-log.txt").exists()


@walks
def test_an_existing_file_is_never_replaced_force_or_not(
    placed: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    target = placed / "out.txt"
    target.write_bytes(b"mine")
    for force in ([], ["--force"]):
        assert get("-o", "out.txt", *force) == cli.EXIT_ERROR
        assert "never replaces a file (--force included)" in capsys.readouterr().err
    assert target.read_bytes() == b"mine"
    assert parts(placed) == []


@walks
def test_a_name_taken_during_the_download_is_kept(
    placed: Path, served: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    def racing(s: Any) -> tuple[int, bytes]:
        (placed / "late.txt").write_bytes(b"theirs")
        return 200, b"hello"

    served.routes[("GET", f"{P}/attachments/att-0042/content")] = racing
    assert get("-o", "late.txt", "--force") == cli.EXIT_ERROR
    assert (placed / "late.txt").read_bytes() == b"theirs"
    assert parts(placed) == []


@walks
def test_a_mismatch_keeps_nothing(placed: Path, served: fakehub.FakeHub) -> None:
    served.routes[("GET", f"{P}/attachments/att-0042/content")] = lambda s: (200, b"HELLO")
    assert get("-o", "o.txt") == cli.EXIT_ERROR
    assert not (placed / "o.txt").exists() and parts(placed) == []


def test_without_descriptors_maity_writes_no_file_but_standard_output_works(
    placed: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(inclone, "WALKS", False)
    assert get("-o", "o.txt") == cli.EXIT_ERROR
    assert "cannot open a file without following links" in capsys.readouterr().err
    assert not (placed / "o.txt").exists()
    assert get("-o", "-") == cli.EXIT_OK


def test_a_session_without_the_runners_git_inode_writes_nothing(
    placed: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(clonecheck.GIT_INODE_ENV)
    assert get("-o", "o.txt") == cli.EXIT_ERROR
    assert not (placed / "o.txt").exists()


def test_outside_a_placement_force_still_replaces_and_any_path_is_taken(
    joined: Path, served: fakehub.FakeHub, tmp_path: Path
) -> None:
    target = tmp_path / "out.txt"
    target.write_bytes(b"mine")
    assert get("-o", str(target), "--force") == cli.EXIT_OK
    assert target.read_bytes() == b"hello"
    assert get("-o", ".git/fetched") == cli.EXIT_OK  # unchanged: no placement, no confinement
    assert (Path.cwd() / ".git" / "fetched").read_bytes() == b"hello"


@walks
def test_a_root_exchanged_after_the_check_is_not_written_to(
    placed: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The walk starts at the root `opened_clone` checked with `.git`, by its descriptor: a
    directory put at the clone's path after the check gets nothing."""
    checked = clonecheck.opened_clone
    moved = placed.parent / "moved"

    @contextlib.contextmanager
    def then_exchanged(root: Path) -> Iterator[clonecheck.Opened | None]:
        with checked(root) as opened:
            os.rename(placed, moved)
            placed.mkdir()
            yield opened

    monkeypatch.setattr(clonecheck, "opened_clone", then_exchanged)
    assert get("-o", str(placed / "out.txt")) == cli.EXIT_OK
    assert (moved / "out.txt").read_bytes() == b"hello"
    assert not (placed / "out.txt").exists()


@walks
@pytest.mark.parametrize("how", ["as-is", "named", "named-no-proc", "no-hard-links"])
def test_the_checked_bytes_are_what_gets_the_name(
    placed: Path, served: fakehub.FakeHub, monkeypatch: pytest.MonkeyPatch, how: str
) -> None:
    """While the download runs, another file takes the name of maity's file (`.maity-*.part`
    beside the target). What gets the target's name is the file maity wrote and checked, or
    nothing: never the other one. `as-is` is this system's way (a file without a name on
    Linux); the others force a named file, without /proc, and without hard links."""
    if how != "as-is":
        monkeypatch.delattr(os, "O_TMPFILE", raising=False)
    if how == "named-no-proc":
        monkeypatch.setattr(inclone, "PROC_FD", str(placed / "no-proc"))
    if how == "no-hard-links":
        real_link = os.link

        def no_link(*args: Any, **kwargs: Any) -> None:
            raise OSError(errno.EPERM, "no hard links here")

        monkeypatch.setattr(os, "link", no_link)
    other = placed.parent / "other"

    def racing(s: Any) -> tuple[int, bytes]:
        for part in placed.glob(".maity-*.part"):
            other.write_bytes(b"OTHER")
            os.replace(other, part)
        return 200, b"hello"

    served.routes[("GET", f"{P}/attachments/att-0042/content")] = racing
    code = get("-o", "out.txt")
    if how == "no-hard-links":
        monkeypatch.setattr(os, "link", real_link)
    target = placed / "out.txt"
    if how == "named-no-proc":
        assert code == cli.EXIT_ERROR and not target.exists()
    else:
        assert code == cli.EXIT_OK and target.read_bytes() == b"hello"
    assert parts(placed) == []


@posix
@walks
@pytest.mark.parametrize("target", ["hooks/post-checkout", "maity/git"])
def test_a_link_put_at_the_clones_path_after_the_check_gets_nothing(
    placed: Path, monkeypatch: pytest.MonkeyPatch, target: str
) -> None:
    """After the check, the clone's path names a link into its own `.git`: the walk still
    starts at the root that was checked, so nothing lands under `.git`."""
    checked = clonecheck.opened_clone
    moved = placed.parent / "moved"

    @contextlib.contextmanager
    def then_linked(root: Path) -> Iterator[clonecheck.Opened | None]:
        with checked(root) as opened:
            os.rename(placed, moved)
            placed.symlink_to(moved / ".git", target_is_directory=True)
            yield opened

    monkeypatch.setattr(clonecheck, "opened_clone", then_linked)
    before = {p: p.read_bytes() for p in (placed / ".git").rglob("*") if p.is_file()}
    for given in (str(placed / target), target):
        assert get("-o", given, "--force") == cli.EXIT_ERROR
    after = {p: p.read_bytes() for p in (moved / ".git").rglob("*") if p.is_file()}
    assert {p.relative_to(placed): b for p, b in before.items()} == {
        p.relative_to(moved): b for p, b in after.items()
    }


@walks
def test_a_copy_whose_name_was_taken_meanwhile_is_not_reported_saved(
    placed: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Without hard links the file is copied under its name; when another file takes that
    name during the copy, the copy is refused like the link, and the other file is left as
    it is."""
    monkeypatch.delattr(os, "O_TMPFILE", raising=False)

    def no_link(*args: Any, **kwargs: Any) -> None:
        raise OSError(errno.EPERM, "no hard links here")

    monkeypatch.setattr(os, "link", no_link)
    real_pread = os.pread
    target = placed / "out.txt"
    other = placed.parent / "other"

    def taken(fd: int, size: int, offset: int) -> bytes:
        if offset == 0 and target.exists():
            target.rename(placed.parent / "ours-moved")
            other.write_bytes(b"OTHER")
            os.replace(other, target)
        return real_pread(fd, size, offset)

    monkeypatch.setattr(os, "pread", taken)
    assert get("-o", "out.txt") == cli.EXIT_ERROR
    assert "was replaced before it got its name" in capsys.readouterr().err
    assert target.read_bytes() == b"OTHER"
    assert parts(placed) == []


@walks
def test_a_link_whose_name_was_taken_meanwhile_is_refused_and_left_alone(
    placed: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """As with the copy: another file at the target's name right after the link is refused,
    and that file is left as it is."""
    real_link = os.link
    target = placed / "out.txt"
    other = placed.parent / "other"

    def then_taken(*args: Any, **kwargs: Any) -> None:
        real_link(*args, **kwargs)
        target.rename(placed.parent / "ours-moved")
        other.write_bytes(b"OTHER")
        os.replace(other, target)

    monkeypatch.setattr(os, "link", then_taken)
    assert get("-o", "out.txt") == cli.EXIT_ERROR
    assert "was replaced before it got its name" in capsys.readouterr().err
    assert target.read_bytes() == b"OTHER"
    assert parts(placed) == []
