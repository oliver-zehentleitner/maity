"""A placement's scratch made, measured and removed from the workspaces root down (§15.5)."""

from __future__ import annotations

import contextlib
import os
import stat
from pathlib import Path
from typing import Any

import pytest
from conftest import posix

from maity.runner import scratchop

pytestmark = [
    posix,
    pytest.mark.skipif(not scratchop.supported(), reason="no descriptor-relative removal here"),
]


@pytest.fixture(autouse=True)
def _restore_modes(tmp_path: Path) -> Any:
    """The tests leave unlistable (0300) or read-only directories behind by design; widen every
    directory at teardown so pytest's own cleanup of its temporary directory can remove them."""
    yield
    for root, dirs, _files in os.walk(tmp_path, topdown=True):
        for name in dirs:  # top-down: widening a directory lets os.walk then descend into it
            with contextlib.suppress(OSError):
                os.chmod(os.path.join(root, name), 0o700)


def _room(root: Path) -> Path:
    return root / "maity" / ".scratch" / "plc-0003"


def _home(root: Path) -> Path:
    return _room(root) / "codex-home"


def test_made_with_tmp_measured_and_removed(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    root.mkdir()
    room = _room(root)
    assert scratchop.make(str(root), str(room)) == {"result": "made"}
    assert stat.S_IMODE((room / "tmp").stat().st_mode) == 0o700
    (room / "tmp" / "venv.bin").write_bytes(b"z" * 4000)
    (room / "loop").symlink_to(tmp_path)  # measured as a link, never followed
    found = scratchop.size(str(root), str(room))
    assert found["result"] == "size" and isinstance(found["bytes"], int)
    assert 4000 <= found["bytes"] < 64 * 1024
    removed = scratchop.remove(str(root), str(room))
    assert removed["result"] == "removed" and removed["bytes"] == found["bytes"]
    assert not room.exists() and tmp_path.is_dir()
    assert scratchop.remove(str(root), str(room)) == {"result": "missing"}
    assert scratchop.size(str(root), str(room)) == {"result": "missing"}
    assert scratchop.remove(str(tmp_path / "none"), str(_room(tmp_path / "none"))) == {
        "result": "missing"
    }


@pytest.mark.parametrize("linked", ["scratch", "holder", "project"])
def test_nothing_is_made_or_removed_through_a_link_on_the_way(tmp_path: Path, linked: str) -> None:
    root = tmp_path / "ws"
    room = _room(root)
    at = {"scratch": room, "holder": room.parent, "project": room.parent.parent}[linked]
    elsewhere = tmp_path / "elsewhere"
    outside = elsewhere / room.relative_to(at)
    (outside / "tmp").mkdir(parents=True)
    (outside / "keep").write_text("k")
    at.parent.mkdir(parents=True, exist_ok=True)
    at.symlink_to(elsewhere)
    for op in (scratchop.make, scratchop.remove, scratchop.size):
        with pytest.raises(scratchop.OnTheWay):
            op(str(root), str(room))
    assert (outside / "keep").read_text() == "k"


@pytest.mark.parametrize(
    "name", ["maity/agent-3", "maity/.scratch", "maity/.scratch/plc-0003/tmp", "maity/x/plc-0003",
             ".scratch/plc-0003", "maity/.scratch/agent-3", "Maity/.scratch/plc-0003"],
)  # fmt: skip
def test_only_a_placements_scratch_is_made_measured_or_removed(tmp_path: Path, name: str) -> None:
    """A clone, the holder `.scratch` itself, anything below a scratch or of another shape:
    refused for every operation, and nothing there is touched."""
    root = tmp_path / "ws"
    target = root / name
    (target / "tmp").mkdir(parents=True)
    (target / "keep").write_text("k")
    for op in (scratchop.make, scratchop.size, scratchop.remove):
        with pytest.raises(OSError) as refused:
            op(str(root), str(target))
        assert not isinstance(refused.value, scratchop.OnTheWay)
    assert (target / "keep").read_text() == "k"


def test_a_scratch_shaped_path_under_another_root_is_refused(tmp_path: Path) -> None:
    room = _room(tmp_path / "other")
    (room / "tmp").mkdir(parents=True)
    with pytest.raises(OSError):
        scratchop.remove(str(tmp_path / "ws"), str(room))
    assert (room / "tmp").is_dir()


def test_the_workspaces_root_is_not_made(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    with pytest.raises(FileNotFoundError):
        scratchop.make(str(root), str(_room(root)))
    assert not root.exists()


def test_a_path_outside_the_root_is_refused(tmp_path: Path) -> None:
    with pytest.raises(OSError, match="not a placement's scratch"):
        scratchop.remove(str(tmp_path / "ws"), str(tmp_path / "ws" / ".." / "x"))
    with pytest.raises(OSError, match="not inside"):
        scratchop.remove(str(tmp_path / "ws"), str(tmp_path / "other"))


def test_the_module_answers_in_one_line_and_says_link_by_its_exit_code(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "ws"
    root.mkdir()
    room = _room(root)
    assert scratchop.main(["make", "--under", str(root), str(room)]) == 0
    assert capsys.readouterr().out.strip() == '{"result": "made"}'
    (root / "other").mkdir()
    (root / "maity" / ".scratch" / "plc-0004").symlink_to(root / "other")
    assert scratchop.main(["remove", "--under", str(root), str(_room(root).parent / "plc-0004")]) \
        == scratchop.LINK  # fmt: skip
    assert '"result": "link"' in capsys.readouterr().out
    assert (root / "other").is_dir()
    assert scratchop.main(["bogus"]) == 2


def test_a_holder_swapped_for_a_link_after_it_was_opened_leads_nowhere_else(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "ws"
    root.mkdir()
    room = _room(root)
    scratchop.make(str(root), str(room))
    (room / "tmp" / "evidence").write_text("e")
    victim = tmp_path / "victim" / "plc-0003"
    victim.mkdir(parents=True)
    (victim / "keep").write_text("k")
    measure = scratchop._size

    def swapped(fd: int) -> int:
        # Between the walk and the removal: `.scratch` moved away, a link in its place.
        room.parent.rename(root / "maity" / "moved")
        room.parent.symlink_to(victim.parent)
        return measure(fd)

    monkeypatch.setattr(scratchop, "_size", swapped)
    assert scratchop.remove(str(root), str(room))["result"] == "removed"
    assert (victim / "keep").read_text() == "k"  # the link's target is untouched
    assert not (root / "maity" / "moved" / "plc-0003").exists()  # what was opened went


def test_a_scratch_swapped_for_a_link_while_it_is_removed_leads_nowhere_else(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The scratch itself replaced by a link between measuring and removing: what was
    measured is what is emptied, the link's target is untouched, and the name is left."""
    root = tmp_path / "ws"
    root.mkdir()
    room = _room(root)
    scratchop.make(str(root), str(room))
    (room / "tmp" / "evidence").write_text("e")
    victim = tmp_path / "victim"
    victim.mkdir()
    (victim / "keep").write_text("k")
    measure = scratchop._size

    def swapped(fd: int) -> int:
        room.rename(room.parent / "moved")
        room.symlink_to(victim)
        return measure(fd)

    monkeypatch.setattr(scratchop, "_size", swapped)
    with pytest.raises(scratchop.OnTheWay):
        scratchop.remove(str(root), str(room))
    assert (victim / "keep").read_text() == "k"
    assert room.is_symlink() and not (room.parent / "moved" / "tmp").exists()


def test_the_size_counts_a_link_not_what_it_points_to(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    root.mkdir()
    room = _room(root)
    scratchop.make(str(root), str(room))
    big = tmp_path / "big"
    big.mkdir()
    (big / "blob").write_bytes(b"z" * 200_000)
    (room / "tmp" / "to-dir").symlink_to(big)
    (room / "tmp" / "to-file").symlink_to(big / "blob")
    found = scratchop.size(str(root), str(room))
    assert isinstance(found["bytes"], int) and found["bytes"] < 64 * 1024


def test_codex_writes_the_control_files_anchored_in_the_home(tmp_path: Path) -> None:
    """config.toml (0600) and the auth.json link land inside a codex-home made 0700 under the
    scratch; the leaf names are reached from the workspaces root without following a link."""
    root = tmp_path / "ws"
    root.mkdir()
    room = _room(root)
    scratchop.make(str(root), str(room))
    login = tmp_path / "login" / "auth.json"
    login.parent.mkdir(parents=True)
    login.write_text("{}")
    assert scratchop.codex(str(root), str(_home(root)), "CONFIG", str(login)) == {
        "result": "written"
    }
    home = _home(root)
    assert home.is_dir() and stat.S_IMODE(home.stat().st_mode) == 0o700
    assert (home / "config.toml").read_text() == "CONFIG"
    assert stat.S_IMODE((home / "config.toml").stat().st_mode) == 0o600
    assert home.joinpath("auth.json").is_symlink()
    assert os.readlink(home / "auth.json") == str(login)


def test_codex_without_a_login_links_no_auth(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    root.mkdir()
    scratchop.make(str(root), str(_room(root)))
    scratchop.codex(str(root), str(_home(root)), "CONFIG", None)
    assert (_home(root) / "config.toml").read_text() == "CONFIG"
    assert not (_home(root) / "auth.json").exists()


def test_codex_refuses_a_codex_home_that_is_a_directory_link(tmp_path: Path) -> None:
    """codex-home replaced by a link to a directory outside the scratch: the no-follow open of
    the leaf fails, the whole operation is refused, and nothing outside it is written."""
    root = tmp_path / "ws"
    root.mkdir()
    room = _room(root)
    scratchop.make(str(root), str(room))
    victim = tmp_path / "victim"
    victim.mkdir()
    (victim / "config.toml").write_text("keep")
    (victim / "auth.json").write_text("keep")
    (room / "codex-home").symlink_to(victim)
    login = tmp_path / "login" / "auth.json"
    login.parent.mkdir(parents=True)
    login.write_text("{}")
    with pytest.raises(scratchop.OnTheWay):
        scratchop.codex(str(root), str(_home(root)), "CONFIG", str(login))
    assert (victim / "config.toml").read_text() == "keep"
    assert (victim / "auth.json").read_text() == "keep"
    assert (room / "codex-home").is_symlink()


def test_codex_replaces_a_leaf_link_without_following_it(tmp_path: Path) -> None:
    """A link planted at config.toml or auth.json (a leaf) is replaced, not followed: the file
    it pointed at outside the scratch is left untouched, the real files land in the home."""
    root = tmp_path / "ws"
    root.mkdir()
    scratchop.make(str(root), str(_room(root)))
    home = _home(root)
    home.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "c").write_text("keep-c")
    (outside / "a").write_text("keep-a")
    (home / "config.toml").symlink_to(outside / "c")
    (home / "auth.json").symlink_to(outside / "a")
    login = tmp_path / "login" / "auth.json"
    login.parent.mkdir(parents=True)
    login.write_text("{}")
    scratchop.codex(str(root), str(home), "CONFIG", str(login))
    assert (outside / "c").read_text() == "keep-c"  # the leaf link was not followed
    assert (outside / "a").read_text() == "keep-a"
    assert not (home / "config.toml").is_symlink()
    assert (home / "config.toml").read_text() == "CONFIG"
    assert os.readlink(home / "auth.json") == str(login)


def test_codex_refuses_a_link_on_the_way_to_the_scratch(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    room = _room(root)
    elsewhere = tmp_path / "elsewhere"
    (elsewhere / "plc-0003").mkdir(parents=True)
    room.parent.mkdir(parents=True)  # <root>/maity/.scratch
    (room).symlink_to(elsewhere / "plc-0003")
    with pytest.raises(scratchop.OnTheWay):
        scratchop.codex(str(root), str(_home(root)), "CONFIG", None)


def test_codex_answers_in_one_line_and_says_link_by_its_exit_code(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "ws"
    root.mkdir()
    scratchop.make(str(root), str(_room(root)))
    monkeypatch.setattr("sys.stdin", _Stdin("CONFIG"))
    assert scratchop.main(["codex", "--under", str(root), str(_home(root))]) == 0
    assert capsys.readouterr().out.strip() == '{"result": "written"}'
    assert (_home(root) / "config.toml").read_text() == "CONFIG"
    (_home(root)).rename(_room(root) / "moved")
    (_home(root)).symlink_to(tmp_path)
    monkeypatch.setattr("sys.stdin", _Stdin("CONFIG"))
    assert scratchop.main(["codex", "--under", str(root), str(_home(root))]) == scratchop.LINK
    assert '"result": "link"' in capsys.readouterr().out
    assert scratchop.main(["codex", "--under", str(root)]) == 2  # no HOME operand


class _Stdin:
    def __init__(self, text: str) -> None:
        self._text = text

    def read(self) -> str:
        return self._text


def test_through_sudo_or_ssh_a_link_on_the_way_is_its_own_answer(tmp_path: Path) -> None:
    import subprocess

    from maity.runner.asuser import AsUser

    class Remote(AsUser):
        """The agents' side as another user: `scratchop` answers by its exit code."""

        def __init__(self, code: int, out: str = "") -> None:
            object.__setattr__(self, "user", "agents")
            object.__setattr__(self, "answer", (code, out))

        def run(self, argv: Any, env: Any = None, input: Any = None, cwd: Any = None,
                timeout: float = 0) -> subprocess.CompletedProcess[str]:  # fmt: skip
            code, out = self.answer  # type: ignore[attr-defined]
            return subprocess.CompletedProcess(argv, code, out, "")

    room = _room(tmp_path / "ws")
    with pytest.raises(scratchop.OnTheWay):  # logged once by the supervisor, not retried
        Remote(scratchop.LINK).scratch("remove", tmp_path / "ws", room)
    with pytest.raises(OSError) as failed:
        Remote(2).scratch("remove", tmp_path / "ws", room)  # a host maity without it
    assert not isinstance(failed.value, scratchop.OnTheWay)
    answer = Remote(0, '{"result": "removed", "bytes": 7}').scratch("remove", tmp_path / "ws", room)
    assert answer == {"result": "removed", "bytes": 7}


def test_through_ssh_a_host_maity_too_old_for_the_codex_op_is_its_own_answer(
    tmp_path: Path,
) -> None:
    """The codex launch-write reaches an ssh host through its own `maity runner scratchop
    codex`. A host whose `maity` has no codex op rejects the subcommand as an argument error
    (exit 2): that is turned into Unsupported, distinct from a LINK (OnTheWay) and a genuine
    failure, so the caller refuses the placement rather than crash-looping it."""
    import subprocess

    from maity.runner.asuser import AsUser

    class Remote(AsUser):
        def __init__(self, code: int, err: str = "") -> None:
            object.__setattr__(self, "user", "agents")
            object.__setattr__(self, "answer", (code, err))

        def run(self, argv: Any, env: Any = None, input: Any = None, cwd: Any = None,
                timeout: float = 0) -> subprocess.CompletedProcess[str]:  # fmt: skip
            code, err = self.answer  # type: ignore[attr-defined]
            return subprocess.CompletedProcess(argv, code, "", err)

    home = _home(tmp_path / "ws")
    with pytest.raises(scratchop.Unsupported) as old:  # exit 2: the op is unknown on the host
        Remote(2, "invalid choice: 'codex'").codex(tmp_path / "ws", home, "CONFIG", None)
    assert not isinstance(old.value, scratchop.OnTheWay)
    with pytest.raises(scratchop.OnTheWay):  # a link where codex-home must be, not too-old
        Remote(scratchop.LINK).codex(tmp_path / "ws", home, "CONFIG", None)
    with pytest.raises(OSError) as failed:  # a genuine failure stays an ordinary OSError
        Remote(1, "boom").codex(tmp_path / "ws", home, "CONFIG", None)
    assert not isinstance(failed.value, (scratchop.OnTheWay, scratchop.Unsupported))
    Remote(0).codex(tmp_path / "ws", home, "CONFIG", None)  # 0: written, no raise


# --- agy's scratch under the host's shared temp directory (workspace.tmp_scratch_of) ----------

# A per-placement leaf name of the shape the runner chooses (scratchop.TMP_LEAF): an unguessable
# token, never a placement id.
LEAF = "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
LEAF2 = "0f1e2d3c4b5a69788796a5b4c3d2e1f0"


def _tmp_room(base: Path, uid: int, leaf: str = LEAF) -> Path:
    """A shared-temp agy scratch under `base`: `<base>/maity-scratch-<uid>/<leaf>`."""
    return base / f"maity-scratch-{uid}" / leaf


def test_a_tmp_scratch_is_made_measured_and_removed(tmp_path: Path) -> None:
    uid = os.getuid()
    room = _tmp_room(tmp_path, uid)
    assert scratchop.tmp_make(str(room)) == {"result": "made"}
    # The parent is unlistable (write + search, no read); the leaf and its `tmp` are private.
    assert stat.S_IMODE(room.parent.stat().st_mode) == scratchop.TMP_PARENT_MODE == 0o300
    assert stat.S_IMODE(room.stat().st_mode) == scratchop.TMP_LEAF_MODE == 0o700
    assert stat.S_IMODE((room / "tmp").stat().st_mode) == 0o700
    (room / "tmp" / "review.json").write_bytes(b"z" * 4000)
    found = scratchop.tmp_size(str(room))
    assert found["result"] == "size" and isinstance(found["bytes"], int)
    assert 4000 <= found["bytes"] < 64 * 1024
    removed = scratchop.tmp_remove(str(room))
    assert removed["result"] == "removed" and removed["bytes"] == found["bytes"]
    assert not room.exists() and room.parent.is_dir()  # only the leaf goes; the parent stays
    assert scratchop.tmp_remove(str(room)) == {"result": "missing"}
    assert scratchop.tmp_size(str(room)) == {"result": "missing"}


def test_the_parent_is_unlistable_and_the_leaf_name_is_unguessable(tmp_path: Path) -> None:
    """The per-user parent is shared across a user's placements but kept unlistable (0300): its
    owner reaches a named leaf but cannot enumerate the names, and the leaf name is an
    unguessable token, so a placement of the same user can neither list nor guess another's."""
    uid = os.getuid()
    first, second = _tmp_room(tmp_path, uid, LEAF), _tmp_room(tmp_path, uid, LEAF2)
    scratchop.tmp_make(str(first))
    scratchop.tmp_make(str(second))
    assert first.is_dir() and second.is_dir() and first.parent == second.parent
    assert stat.S_IMODE(first.parent.stat().st_mode) == 0o300  # no read bit: not listable
    if os.getuid() != 0:  # root ignores the mode; the mode on disk is asserted above regardless
        with pytest.raises(PermissionError):
            os.listdir(first.parent)  # even its owner cannot list the names
    # A placement still reaches its own leaf by the recorded name, not by listing the parent.
    assert scratchop.tmp_size(str(first))["result"] == "size"


@pytest.mark.parametrize("planted", ["dir", "symlink"])
def test_a_pre_existing_leaf_is_refused_and_left_alone(tmp_path: Path, planted: str) -> None:
    """A leaf already there when the scratch is made — a directory, or a link out of it —
    is refused: a placement's scratch is made fresh, never reused or written through."""
    uid = os.getuid()
    room = _tmp_room(tmp_path, uid)
    room.parent.mkdir(mode=0o300)  # a sound per-user parent (unlistable, this uid's own)
    outside = tmp_path / "outside"
    (outside).mkdir()
    (outside / "keep").write_text("k")
    if planted == "symlink":
        room.symlink_to(outside)
    else:
        room.mkdir()
        (room / "keep").write_text("k")
    with pytest.raises(scratchop.OnTheWay):
        scratchop.tmp_make(str(room))
    assert (outside / "keep").read_text() == "k"  # nothing written through it


@pytest.mark.parametrize("planted", ["symlink", "file", "dir"])
def test_a_tmp_planted_in_the_fresh_leaf_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, planted: str
) -> None:
    """The `tmp` inside the fresh leaf is made with the same fresh, no-follow, owner-and-mode
    discipline, so a sibling of the same user that plants something at `<leaf>/tmp` in the
    window between the leaf's creation and the `tmp`'s is refused, not adopted or followed. The
    race is driven by planting `tmp` right after the leaf is made fresh."""
    uid = os.getuid()
    room = _tmp_room(tmp_path, uid)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep").write_text("k")
    real_tmp_dir = scratchop._tmp_dir

    def planting(
        dir_fd: int, name: str, u: int, mode: int, *, fresh: bool, path_fd: bool = False
    ) -> int:
        fd = real_tmp_dir(dir_fd, name, u, mode, fresh=fresh, path_fd=path_fd)
        if name == LEAF:  # the leaf is now fresh: a same-user sibling plants its `tmp`
            with contextlib.suppress(FileExistsError):
                if planted == "symlink":
                    os.symlink(str(outside), "tmp", dir_fd=fd)
                elif planted == "file":
                    os.close(os.open("tmp", os.O_CREAT | os.O_WRONLY, 0o600, dir_fd=fd))
                else:
                    os.mkdir("tmp", 0o700, dir_fd=fd)
        return fd

    monkeypatch.setattr(scratchop, "_tmp_dir", planting)
    with pytest.raises(scratchop.OnTheWay):
        scratchop.tmp_make(str(room))
    assert (outside / "keep").read_text() == "k"  # nothing written through it


@pytest.mark.parametrize("mode", [0o500, 0o555, 0o000])
def test_a_scratch_holding_a_restrictive_directory_is_removed_cleanly(
    tmp_path: Path, mode: int
) -> None:
    """A read-only, unlistable or unsearchable directory a build tool leaves behind (a module
    cache, say) does not leave the scratch undeletable: the owner's access is restored on each
    directory before it is emptied, so remove succeeds and the scratch can be made again (the
    restart path)."""
    uid = os.getuid()
    room = _tmp_room(tmp_path, uid)
    scratchop.tmp_make(str(room))
    locked = room / "tmp" / "cache" / "deep"
    locked.mkdir(parents=True)
    (locked / "f").write_text("x" * 100)
    os.chmod(locked, mode)
    os.chmod(locked.parent, mode)
    try:
        removed = scratchop.tmp_remove(str(room))
    finally:
        for d in (locked, locked.parent):
            if d.exists():
                os.chmod(d, 0o700)  # so pytest can clean up if the remove failed
    assert removed["result"] == "removed"
    assert not room.exists()
    assert scratchop.tmp_make(str(room)) == {"result": "made"}  # the restart path remakes it


def test_a_foreign_owned_parent_is_refused_with_a_distinct_reason(tmp_path: Path) -> None:
    """The per-user parent must be owned by the uid the agents run as; one owned by another is
    refused, and the reason says another user holds the name (not a bare permission error).
    Driven by passing a uid the directory is not owned by (a test cannot chown)."""
    uid = os.getuid()
    foreign = uid + 1  # a uid the parent this test makes is not owned by
    room = _tmp_room(tmp_path, foreign)
    room.parent.mkdir(mode=0o700)  # owned by this test's uid, not `foreign`
    with pytest.raises(scratchop.OnTheWay, match="held by another user"):
        scratchop.tmp_make(str(room), uid=foreign)
    assert not room.exists()


def test_a_foreign_owned_leaf_is_refused_on_remove(tmp_path: Path) -> None:
    """Remove checks the leaf is this uid's own (its mode is not required, so an agent widening
    its own leaf cannot block cleanup) — one owned by another user is not removed."""
    uid = os.getuid()
    foreign = uid + 1
    room = _tmp_room(tmp_path, foreign)
    room.parent.mkdir(mode=0o300)
    room.mkdir(mode=0o700)
    (room / "keep").write_text("k")
    with pytest.raises(scratchop.OnTheWay, match="held by another user"):
        scratchop.tmp_remove(str(room), uid=foreign)
    assert (room / "keep").read_text() == "k"  # left as it is


def test_a_widened_leaf_is_still_removed(tmp_path: Path) -> None:
    """An agent that widened its own leaf's mode cannot stop its own cleanup: remove requires
    ownership, not a particular mode."""
    uid = os.getuid()
    room = _tmp_room(tmp_path, uid)
    scratchop.tmp_make(str(room))
    os.chmod(room, 0o777)  # noqa: S103 - the agent widens its own leaf, deliberately here
    assert scratchop.tmp_remove(str(room))["result"] == "removed"
    assert not room.exists()


def test_a_symlinked_parent_is_refused_and_leads_nowhere(tmp_path: Path) -> None:
    uid = os.getuid()
    real = tmp_path / "real"
    real.mkdir()
    (real / "keep").write_text("k")
    parent = tmp_path / f"maity-scratch-{uid}"
    parent.symlink_to(real)
    with pytest.raises(scratchop.OnTheWay):
        scratchop.tmp_make(str(_tmp_room(tmp_path, uid)))
    assert not (real / LEAF).exists()  # nothing written through the link


@pytest.mark.parametrize("kind", ["non-numeric-uid", "other-uid", "bad-leaf"])
def test_a_badly_shaped_tmp_path_is_refused(tmp_path: Path, kind: str) -> None:
    """A non-numeric or mismatched uid parent, or a leaf that is not a chosen token: an
    ordinary OSError (not OnTheWay), before anything is made."""
    uid = os.getuid()
    names = {
        "non-numeric-uid": f"maity-scratch-x/{LEAF}",
        "other-uid": f"maity-scratch-{uid + 1}/{LEAF}",
        "bad-leaf": f"maity-scratch-{uid}/plc-0003",
    }
    given = tmp_path / names[kind]
    with pytest.raises(OSError) as refused:
        scratchop.tmp_make(str(given))
    assert not isinstance(refused.value, scratchop.OnTheWay)
    assert not given.exists()


@pytest.mark.parametrize("kind", ["relative", "dotdot", "leading-zero-uid", "symlinked-root"])
def test_a_path_not_under_a_real_absolute_root_is_refused(tmp_path: Path, kind: str) -> None:
    """Defence in depth on the path itself (parity with the beside-clone `_below`): a relative
    path, a `..` on the way, a non-canonical (leading-zero) uid, or a root reached through a
    link is refused with an ordinary OSError before anything is opened."""
    uid = os.getuid()
    if kind == "relative":
        given: Path = Path(f"maity-scratch-{uid}") / LEAF
    elif kind == "dotdot":
        given = tmp_path / ".." / tmp_path.name / f"maity-scratch-{uid}" / LEAF
    elif kind == "leading-zero-uid":
        given = tmp_path / f"maity-scratch-0{uid}" / LEAF  # "0<uid>" is not the canonical uid
    else:  # a shared-temp root reached through a link (a `/tmp` that is itself a link)
        real = tmp_path / "real"
        real.mkdir()
        link = tmp_path / "link"
        link.symlink_to(real)
        given = link / f"maity-scratch-{uid}" / LEAF
    with pytest.raises(OSError) as refused:
        scratchop.tmp_make(str(given))
    assert not isinstance(refused.value, scratchop.OnTheWay)


def test_the_tmp_module_answers_in_one_line_and_says_link_by_its_exit_code(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    uid = os.getuid()
    room = _tmp_room(tmp_path, uid)
    assert scratchop.main(["tmpmake", str(room)]) == 0
    assert capsys.readouterr().out.strip() == '{"result": "made"}'
    scratchop.tmp_remove(str(room))
    room.symlink_to(tmp_path)  # a link where the fresh leaf must be
    assert scratchop.main(["tmpmake", str(room)]) == scratchop.LINK
    assert '"result": "link"' in capsys.readouterr().out
    assert scratchop.main(["tmpmake"]) == 2  # no path
