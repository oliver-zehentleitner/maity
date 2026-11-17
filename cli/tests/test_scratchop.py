"""A placement's scratch made, measured and removed from the workspaces root down (§15.5)."""

from __future__ import annotations

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


def _room(root: Path) -> Path:
    return root / "maity" / ".scratch" / "plc-0003"


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
