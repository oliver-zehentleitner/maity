"""A placement's scratch made, measured and removed from the workspaces root down (§15.5)."""

from __future__ import annotations

import stat
from pathlib import Path

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


def test_a_path_outside_the_root_is_refused(tmp_path: Path) -> None:
    with pytest.raises(OSError, match="not inside"):
        scratchop.remove(str(tmp_path / "ws"), str(tmp_path / "ws" / ".." / "x"))
    with pytest.raises(OSError, match="not inside"):
        scratchop.remove(str(tmp_path / "ws"), str(tmp_path / "other"))


def test_the_module_answers_in_one_line_and_says_link_by_its_exit_code(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "ws"
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
