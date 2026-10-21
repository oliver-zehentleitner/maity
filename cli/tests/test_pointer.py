from __future__ import annotations

from pathlib import Path

from maity import pointer


def test_block_is_appended_once(tmp_path: Path) -> None:
    agents = tmp_path / "AGENTS.md"
    agents.write_text("# AGENTS.md\n\nRules.")
    assert pointer.write(tmp_path) == [agents]
    assert pointer.write(tmp_path) == []
    text = agents.read_text()
    assert text.startswith("# AGENTS.md\n\nRules.\n\n" + pointer.BEGIN)
    assert text.count(pointer.BEGIN) == 1


def test_block_is_refreshed_in_place(tmp_path: Path) -> None:
    agents = tmp_path / "AGENTS.md"
    agents.write_text(f"head\n\n{pointer.BEGIN}\nold\n{pointer.END}\ntail\n")
    pointer.write(tmp_path)
    assert agents.read_text() == f"head\n\n{pointer.BLOCK}tail\n"


def test_agents_md_is_created_when_missing(tmp_path: Path) -> None:
    pointer.write(tmp_path)
    assert (tmp_path / "AGENTS.md").read_text() == pointer.BLOCK


def test_claude_md_only_when_it_does_not_import_agents_md(tmp_path: Path) -> None:
    (tmp_path / "CLAUDE.md").write_text("@AGENTS.md\n")
    assert pointer.write(tmp_path) == [tmp_path / "AGENTS.md"]
    (tmp_path / "CLAUDE.md").write_text("# Own rules\n")
    assert pointer.write(tmp_path) == [tmp_path / "CLAUDE.md"]


def test_block_has_no_url_and_no_fetch() -> None:
    assert "http" not in pointer.BLOCK
    assert "maity resume" in pointer.BLOCK
