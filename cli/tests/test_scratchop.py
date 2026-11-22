"""A placement's scratch made, measured and removed from the workspaces root down (§15.5)."""

from __future__ import annotations

import contextlib
import os
import stat
import subprocess
import sys
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
    """The tests leave restrictive (0000/0400/0500) directories behind by design; widen every
    directory at teardown so pytest's own cleanup of its temporary directory can remove them."""
    yield
    for root, dirs, _files in os.walk(tmp_path, topdown=True):
        for name in dirs:  # top-down: widening a directory lets os.walk then descend into it
            with contextlib.suppress(OSError):
                os.chmod(os.path.join(root, name), 0o700)


def _room(root: Path) -> Path:
    return root / ".scratch" / "maity" / "plc-0003"


def _former(root: Path) -> Path:
    return root / "maity" / ".scratch" / "plc-0003"


def _home(root: Path) -> Path:
    return _room(root) / "codex-home"


def test_made_with_tmp_measured_and_removed(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    root.mkdir()
    room = _room(root)
    old = os.umask(0o022)  # the scratch itself made 0700 whatever the umask leaves
    try:
        assert scratchop.make(str(root), str(room)) == {"result": "made"}
    finally:
        os.umask(old)
    assert stat.S_IMODE((room / "tmp").stat().st_mode) == 0o700
    assert stat.S_IMODE(room.stat().st_mode) == 0o700
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


def test_the_pg_password_is_drawn_once_in_the_holder_and_kept(tmp_path: Path) -> None:
    """tsk-w7qtcbzcshn9 (security review of #2032): the test cluster's password, in one holder
    outside every scratch (0700), one 0600 file per placement; a restart keeps it, and it goes
    with the placement."""
    root = tmp_path / "ws"
    root.mkdir()
    holder = root / scratchop.PG_HOLDER
    leaf = holder / "plc-0003"
    old = os.umask(0o000)  # the modes are set, not left to the umask
    try:
        assert scratchop.pg_make(str(root), str(holder)) == {"result": "made"}
        assert scratchop.pg_make(str(root), str(leaf)) == {"result": "made", "pg_pass": True}
    finally:
        os.umask(old)
    assert stat.S_IMODE(holder.stat().st_mode) == 0o700
    first = leaf.read_text()
    assert len(first) == 65 and first.endswith("\n") and int(first, 16) >= 0
    assert stat.S_IMODE(leaf.stat().st_mode) == 0o600
    assert scratchop.pg_read(str(root), str(leaf)) == first.strip()
    assert scratchop.pg_make(str(root), str(leaf))["pg_pass"] is True
    assert leaf.read_text() == first  # kept across a restart
    scratchop.pg_make(str(root), str(holder / "plc-0004"))
    assert (holder / "plc-0004").read_text() != first  # one per placement
    assert scratchop.pg_remove(str(root), str(leaf)) == {"result": "removed"}
    assert not leaf.exists() and scratchop.pg_read(str(root), str(leaf)) is None
    assert scratchop.pg_remove(str(root), str(leaf)) == {"result": "missing"}
    nowhere = tmp_path / "none"
    assert scratchop.pg_remove(str(nowhere), str(nowhere / ".maity-pg" / "plc-0003")) == {
        "result": "missing"
    }


@pytest.mark.parametrize("planted", ["link", "dangling", "wide", "directory", "hardlink"])
def test_a_planted_pg_password_is_never_written_through_read_or_vouched_for(
    tmp_path: Path, planted: str
) -> None:
    root = tmp_path / "ws"
    root.mkdir()
    holder = root / scratchop.PG_HOLDER
    scratchop.pg_make(str(root), str(holder))
    leaf = holder / "plc-0003"
    victim = tmp_path / "victim"
    victim.write_text("keepme")
    if planted == "link":
        leaf.symlink_to(victim)
    elif planted == "dangling":
        leaf.symlink_to(tmp_path / "nowhere")
    elif planted == "wide":
        leaf.write_text("a" * 64 + "\n")
        leaf.chmod(0o644)
    elif planted == "hardlink":  # a 0600 file of this user, but another name holds it too
        victim.chmod(0o600)
        os.link(victim, leaf)
    else:
        leaf.mkdir()
    assert scratchop.pg_make(str(root), str(leaf))["pg_pass"] is False
    assert scratchop.pg_read(str(root), str(leaf)) is None
    assert victim.read_text() == "keepme" and not (tmp_path / "nowhere").exists()


def test_a_directory_planted_as_a_password_file_leaks_no_descriptor(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    root.mkdir()
    holder = root / scratchop.PG_HOLDER
    scratchop.pg_make(str(root), str(holder))
    (holder / "plc-0003").mkdir()
    fds = Path("/proc/self/fd")
    before = len(list(fds.iterdir())) if fds.is_dir() else 0
    for _ in range(5):
        assert scratchop.pg_read(str(root), str(holder / "plc-0003")) is None
    if fds.is_dir():
        assert len(list(fds.iterdir())) == before


def test_a_fifo_planted_as_a_password_file_neither_blocks_nor_is_read(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    root.mkdir()
    holder = root / scratchop.PG_HOLDER
    scratchop.pg_make(str(root), str(holder))
    os.mkfifo(holder / "plc-0003", 0o600)
    assert scratchop.pg_read(str(root), str(holder / "plc-0003")) is None  # returns at once


@pytest.mark.parametrize("planted", ["link", "file", "wide"])
def test_a_planted_holder_is_never_used(tmp_path: Path, planted: str) -> None:
    root = tmp_path / "ws"
    root.mkdir()
    holder = root / scratchop.PG_HOLDER
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir(mode=0o755)
    if planted == "link":
        holder.symlink_to(elsewhere)
    elif planted == "file":
        holder.write_text("x")
    else:  # widened by someone of this user: narrowed again, not refused
        holder.mkdir(mode=0o755)
        holder.chmod(0o755)
    if planted == "wide":
        scratchop.pg_make(str(root), str(holder))
        assert stat.S_IMODE(holder.stat().st_mode) == 0o700
        return
    with pytest.raises(scratchop.OnTheWay):
        scratchop.pg_make(str(root), str(holder / "plc-0003"))
    assert list(elsewhere.iterdir()) == [] and stat.S_IMODE(elsewhere.stat().st_mode) == 0o755


@pytest.mark.parametrize(
    "name", [".maity-pg/agent-3", ".maity-pg/plc-0003/x", "maity/.maity-pg/plc-0003",
             ".scratch", ".maity-pg/.."],
)  # fmt: skip
def test_only_the_holder_or_a_placements_file_in_it(tmp_path: Path, name: str) -> None:
    root = tmp_path / "ws"
    root.mkdir()
    for op in (scratchop.pg_make, scratchop.pg_remove):
        with pytest.raises(OSError) as refused:
            op(str(root), str(root / name))
        assert not isinstance(refused.value, scratchop.OnTheWay)
    assert sorted(os.listdir(root)) == []
    assert scratchop.pg_read(str(root), str(root / name)) is None


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
             ".scratch/plc-0003", "maity/.scratch/agent-3", "Maity/.scratch/plc-0003",
             "maity/.scratch/plc-0003\n", "maity\n/.scratch/plc-0003",
             ".scratch", ".scratch/maity", ".scratch/maity/plc-0003/tmp", ".scratch/Maity/plc-0003",
             ".scratch/maity/agent-3", ".scratch/.scratch/plc-0003", "x/maity/plc-0003"],
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


def test_the_former_shape_is_measured_and_removed_but_never_made(tmp_path: Path) -> None:
    """tsk-c7zzd440x8pn: a scratch a start before the holder made, in
    `<root>/<project>/.scratch/<id>`, is still measured and removed until its placement is gone;
    no scratch is made there any more, nor Codex's home written into one."""
    root = tmp_path / "ws"
    former = _former(root)
    (former / "tmp").mkdir(parents=True)
    (former / "tmp" / "f").write_bytes(b"z" * 100)
    with pytest.raises(OSError, match="not a placement's scratch"):
        scratchop.make(str(root), str(former))
    with pytest.raises(OSError, match="not a placement's scratch"):
        scratchop.codex(str(root), str(former / "codex-home"), "CONFIG", None)
    assert scratchop.size(str(root), str(former))["result"] == "size"
    assert scratchop.remove(str(root), str(former))["result"] == "removed"
    assert not former.exists() and former.parent.is_dir()  # the former holder stays


def test_the_holder_is_made_private_and_checked_at_every_make(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The holder of every scratch is made 0700, and both the holder op and every make check
    it: a link or another user's directory is refused (OnTheWay) and nothing is made in it."""
    root = tmp_path / "ws"
    root.mkdir()
    holder = root / ".scratch"
    assert scratchop.holder(str(root), str(holder)) == {"result": "made"}
    assert stat.S_IMODE(holder.stat().st_mode) == 0o700
    assert scratchop.holder(str(root), str(holder)) == {"result": "made"}  # an existing one
    with pytest.raises(OSError, match="not the scratch holder"):
        scratchop.holder(str(root), str(root / "maity" / ".scratch"))
    # Another user's holder: refused by the op and by make, nothing made under it.
    real = scratchop._uid
    monkeypatch.setattr(scratchop, "_uid", lambda user: real(user) + 1)
    with pytest.raises(scratchop.OnTheWay):
        scratchop.holder(str(root), str(holder))
    with pytest.raises(scratchop.OnTheWay):
        scratchop.make(str(root), str(_room(root)))
    assert not _room(root).exists()
    # Nor is anything removed through another user's holder (A2068); the former shape, which
    # has no holder, is not affected.
    monkeypatch.setattr(scratchop, "_uid", real)
    scratchop.make(str(root), str(_room(root)))
    monkeypatch.setattr(scratchop, "_uid", lambda user: real(user) + 1)
    with pytest.raises(scratchop.OnTheWay):
        scratchop.remove(str(root), str(_room(root)))
    assert _room(root).is_dir()
    # Another user's holder whose mode keeps us out is OnTheWay too, not a bare permission
    # error (A2073); as root the mode keeps nobody out and the owner check says it.
    holder.chmod(0o000)
    try:
        with pytest.raises(scratchop.OnTheWay):
            scratchop.holder(str(root), str(holder))
        with pytest.raises(scratchop.OnTheWay):
            scratchop.remove(str(root), str(_room(root)))
    finally:
        holder.chmod(0o700)
    monkeypatch.setattr(scratchop, "_uid", real)
    assert scratchop.remove(str(root), str(_room(root)))["result"] == "removed"
    # A link in its place: refused, the link's target untouched.
    _room(root).parent.rmdir()  # the project's directory a remove leaves, empty
    holder.rmdir()
    (tmp_path / "elsewhere").mkdir()
    holder.symlink_to(tmp_path / "elsewhere")
    with pytest.raises(scratchop.OnTheWay):
        scratchop.holder(str(root), str(holder))
    with pytest.raises(scratchop.OnTheWay):
        scratchop.make(str(root), str(_room(root)))
    assert list((tmp_path / "elsewhere").iterdir()) == []


def test_the_module_imports_only_the_standard_library_and_maity() -> None:
    """It runs with `-I` on the agents' side and imports only the standard library and maity
    modules that do the same: followed through, no module from anywhere else is loaded."""
    probe = (
        "import sys; before = set(sys.modules); import maity.runner.scratchop; "
        "print('\\n'.join(sorted(m for m in set(sys.modules) - before "
        "if m.split('.')[0] not in sys.stdlib_module_names and m.split('.')[0] != 'maity')))"
    )
    src = str(Path(scratchop.__file__).resolve().parents[2])
    done = subprocess.run(
        [sys.executable, "-I", "-c", f"import sys; sys.path.insert(0, {src!r}); {probe}"],
        capture_output=True, text=True, check=True, timeout=60,
    )  # fmt: skip
    assert done.stdout.strip() == ""


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
    (root / ".scratch" / "maity" / "plc-0004").symlink_to(root / "other")
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
        # Between the walk and the removal: the project's directory moved away, a link in its
        # place.
        room.parent.rename(room.parent.parent / "moved")
        room.parent.symlink_to(victim.parent)
        return measure(fd)

    monkeypatch.setattr(scratchop, "_size", swapped)
    assert scratchop.remove(str(root), str(room))["result"] == "removed"
    assert (victim / "keep").read_text() == "k"  # the link's target is untouched
    assert not (room.parent.parent / "moved" / "plc-0003").exists()  # what was opened went


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
    room.parent.mkdir(parents=True)  # <root>/.scratch/maity
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
    assert not isinstance(failed.value, (scratchop.OnTheWay, scratchop.Unsupported))
    # A host whose maity predates the holder op answers it with a usage error: Unsupported,
    # which the supervisor reads as the former layout there (tsk-c7zzd440x8pn).
    with pytest.raises(scratchop.Unsupported):
        Remote(2).scratch("holder", tmp_path / "ws", tmp_path / "ws" / ".scratch")
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

# A per-placement leaf name of the shape the runner chooses (scratchop.TMP_LEAF): a random
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
    # The parent, the leaf and its `tmp` are all 0700, owned by the user agy runs as.
    assert stat.S_IMODE(room.parent.stat().st_mode) == scratchop.TMP_PARENT_MODE == 0o700
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


def test_the_parent_is_0700_and_holds_each_of_a_users_leaves(tmp_path: Path) -> None:
    """The per-user parent is shared across a user's placements and owned 0700 by that user: it
    is readable and writable by its owner (so maity's own `--review-file` read, which walks it
    O_RDONLY, works) and keeps other host users out. Two placements of the same user get two
    leaves under the one parent; the parent gives them no separation from each other."""
    uid = os.getuid()
    first, second = _tmp_room(tmp_path, uid, LEAF), _tmp_room(tmp_path, uid, LEAF2)
    scratchop.tmp_make(str(first))
    scratchop.tmp_make(str(second))
    assert first.is_dir() and second.is_dir() and first.parent == second.parent
    assert stat.S_IMODE(first.parent.stat().st_mode) == 0o700  # readable by its owner
    assert sorted(os.listdir(first.parent)) == sorted([LEAF, LEAF2])  # its owner lists both leaves
    assert scratchop.tmp_size(str(first))["result"] == "size"


@pytest.mark.parametrize("planted", ["dir", "symlink"])
def test_a_pre_existing_leaf_is_refused_and_left_alone(tmp_path: Path, planted: str) -> None:
    """A leaf already there when the scratch is made — a directory, or a link out of it —
    is refused: a placement's scratch is made fresh, never reused or written through."""
    uid = os.getuid()
    room = _tmp_room(tmp_path, uid)
    room.parent.mkdir(mode=0o700)  # a sound per-user parent (0700, this uid's own)
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

    def planting(dir_fd: int, name: str, u: int, mode: int, *, fresh: bool) -> int:
        fd = real_tmp_dir(dir_fd, name, u, mode, fresh=fresh)
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
    room.parent.mkdir(mode=0o700)
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


@pytest.mark.parametrize("where, mode", [("leaf", 0o000), ("leaf", 0o400), ("subdir", 0o400)])
def test_a_restrictive_leaf_or_subdir_does_not_block_tmp_remove(
    tmp_path: Path, where: str, mode: int
) -> None:
    """A 0000 or 0400 leaf, or such a directory a build tool left inside it, does not raise a
    bare PermissionError out of tmp_remove: the leaf is opened and widened through `_open_below`
    and `_size` tolerates what it cannot stat, so the scratch is removed and can be remade. Red
    on dc826d9b, where `_remove_in` opened the leaf O_RDONLY (a 0000 leaf failed) and `_size`
    suppressed only FileNotFoundError (a 0400 leaf or subdir raised)."""
    uid = os.getuid()
    room = _tmp_room(tmp_path, uid)
    scratchop.tmp_make(str(room))
    target = room if where == "leaf" else room / "tmp" / "cache"
    if where == "subdir":
        target.mkdir()
        (target / "f").write_text("x" * 50)
    os.chmod(target, mode)
    try:
        removed = scratchop.tmp_remove(str(room))
    finally:
        if target.exists():
            os.chmod(target, 0o700)  # so pytest can clean up if the remove failed
    assert removed["result"] == "removed"
    assert not room.exists()
    assert scratchop.tmp_make(str(room)) == {"result": "made"}  # the restart path remakes it


def test_remove_names_a_leaf_this_uid_does_not_own_as_a_clash_not_a_bare_error(
    tmp_path: Path,
) -> None:
    """`_remove_in` opens the leaf through `_open_below`, so a leaf whose own mode denies opening
    it and which this uid does not own is named as a clash (OnTheWay), not raised as a bare
    PermissionError. Driven with a 0000 leaf and a uid it is not owned by (a test cannot chown).
    Red on dc826d9b, where `_remove_in` opened the leaf with `_step` and a 0000 leaf raised
    PermissionError before the owner check could name the clash."""
    uid = os.getuid()
    foreign = uid + 1  # a uid the leaf this test makes is not owned by
    parent = tmp_path / "p"
    parent.mkdir(mode=0o700)
    leaf = parent / "leaf"
    leaf.mkdir(mode=0o700)
    (leaf / "keep").write_text("k")
    os.chmod(leaf, 0o000)
    pfd = os.open(str(parent), os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        with pytest.raises(scratchop.OnTheWay):
            scratchop._remove_in(pfd, "leaf", uid=foreign)
    finally:
        os.close(pfd)
        os.chmod(leaf, 0o700)
    assert (leaf / "keep").read_text() == "k"  # left as it is


@pytest.mark.skipif(not os.path.isdir("/proc/self/fd"), reason="no /proc to count descriptors")
def test_empty_closes_its_descriptors_when_the_walk_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`_empty` closes every descriptor it opens, on an exception mid-walk too: the frames still
    on the stack are dropped in its finally, so a failed removal does not leak fds. Red on
    dc826d9b, where an exception out of the walk left the stacked directory descriptors open."""
    uid = os.getuid()
    room = _tmp_room(tmp_path, uid)
    scratchop.tmp_make(str(room))
    (room / "tmp" / "a" / "b" / "c").mkdir(parents=True)
    real_scan = scratchop._scan
    state = {"n": 0}

    def boom(parent_fd: int, name: str | None, fd: int, uid_: int | None) -> Any:
        state["n"] += 1
        if state["n"] >= 3:  # a couple of child frames are on the stack by now
            raise RuntimeError("mid-walk failure")
        return real_scan(parent_fd, name, fd, uid_)

    monkeypatch.setattr(scratchop, "_scan", boom)
    fd = os.open(str(room), os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    before = len(os.listdir("/proc/self/fd"))
    try:
        with pytest.raises(RuntimeError):
            scratchop._empty(fd, uid)
        assert len(os.listdir("/proc/self/fd")) <= before  # nothing leaked but our own root fd
    finally:
        os.close(fd)


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


def test_the_tmp_parent_op_creates_or_adopts_the_per_user_parent(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`tmpparent` creates the per-user parent 0700, adopts one already this uid's own, and
    normalises a parent narrowed since; a link or a non-canonical path is refused."""
    uid = os.getuid()
    parent = tmp_path / f"maity-scratch-{uid}"
    assert scratchop.main(["tmpparent", str(parent)]) == 0
    assert capsys.readouterr().out.strip() == '{"result": "made"}'
    assert parent.is_dir() and stat.S_IMODE(parent.stat().st_mode) == 0o700
    os.chmod(parent, 0o500)  # narrowed by something since
    assert scratchop.tmp_parent_make(str(parent)) == {"result": "made"}  # adopted and normalised
    assert stat.S_IMODE(parent.stat().st_mode) == 0o700
    with pytest.raises(OSError):  # a non-canonical (other-uid) parent is refused
        scratchop.tmp_parent_make(str(tmp_path / f"maity-scratch-{uid + 1}"))
    assert scratchop.main(["tmpparent"]) == 2  # no path
