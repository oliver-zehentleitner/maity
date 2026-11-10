"""Tests for tools/split_views_context.py.

Standard library only, so CI runs them without installing anything:
    python3 -m unittest discover -s tools -p 'test_*.py'
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import split_views_context as split

BASE = "126b030c58b0586c66abc931ddc36865ed9ec9f4"


def show(path: str) -> str:
    return subprocess.check_output(
        ["git", "-C", str(split.ROOT), "show", f"{BASE}:{path}"], text=True
    )


class Split(unittest.TestCase):
    def test_table_covers_the_views_file_it_was_built_from(self) -> None:
        table = split.load_table()
        entries = split.parse_entries(show("web/context/views.md"))
        self.assertEqual(
            [entry_id for entry_id, _ in table],
            [split.id_of(entry) for entry in entries],
        )

    def test_check_reproduces_the_committed_topic_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "views.md").write_text(show("web/context/views.md"), encoding="utf-8")
            (root / "index.md").write_text(show("web/context/index.md"), encoding="utf-8")
            code = split.main(
                ["--views", str(root / "views.md"), "--index", str(root / "index.md"), "--check"]
            )
        self.assertEqual(code, 0)

    def test_an_unclassified_id_fails(self) -> None:
        entries = split.parse_entries(show("web/context/views.md"))
        extra = (
            "## A new decision\n\n"
            "**Id:** 33333333-3333-4333-8333-333333333333\n"
            "**Status:** active\n\n"
            "Not classified.\n"
        )
        with self.assertRaises(split.Unclassified) as caught:
            split.classify(entries + [extra], split.load_table(), {})
        self.assertEqual(caught.exception.ids, ["33333333-3333-4333-8333-333333333333"])

    def test_a_given_family_classifies_the_new_id(self) -> None:
        entries = split.parse_entries(show("web/context/views.md"))
        extra = (
            "## A new decision\n\n"
            "**Id:** 33333333-3333-4333-8333-333333333333\n"
            "**Status:** active\n\n"
            "Classified on the command line.\n"
        )
        grouped = split.classify(
            entries + [extra],
            split.load_table(),
            {"33333333-3333-4333-8333-333333333333": "shell"},
        )
        self.assertTrue(
            any(split.id_of(entry).startswith("33333333") for entry in grouped["shell"])
        )

    def test_live_scan_ignores_changelog_vendor_and_dashboard_views(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "changelog.d").mkdir()
            (root / "changelog.d" / "old.md").write_text("see web/context/views.md\n", encoding="utf-8")
            vendor = root / "web" / "vendor" / "keep-the-why"
            vendor.mkdir(parents=True)
            (vendor / "README.md").write_text("docs/dashboard-views.md\n", encoding="utf-8")
            (root / "web").mkdir(exist_ok=True)
            (root / "web" / "README.md").write_text(
                "docs/dashboard-views.md is not ours\nsee context/views.md\n",
                encoding="utf-8",
            )
            (root / "tools").mkdir()
            (root / "tools" / "split_views_context.py").write_text(
                "the views.md it is given\n", encoding="utf-8"
            )
            self.assertEqual(split.live_views_references(root), ["web/README.md:2"])
        self.assertEqual(split.views_md_lines("docs/dashboard-views.md\n"), [])
