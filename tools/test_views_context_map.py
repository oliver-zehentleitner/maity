"""Tests for tools/views_context_map.py.

Standard library only, so CI runs them without installing anything:
    python3 -m unittest discover -s tools -p 'test_*.py'
"""

from __future__ import annotations

import io
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import split_views_context as split
import views_context_map as vcm

ONE = "11111111-1111-4111-8111-111111111111"
TWO = "22222222-2222-4222-8222-222222222222"
NEW = "33333333-3333-4333-8333-333333333333"


def entry(heading: str, entry_id: str, body: str) -> str:
    return (
        f"## {heading}\n\n"
        f"**Id:** {entry_id}\n"
        "**Status:** active\n\n"
        f"{body}\n"
    )


class Map(unittest.TestCase):
    def tree(self) -> Path:
        root = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(root))
        context = root / "web" / "context"
        context.mkdir(parents=True)
        (context / "inbox.md").write_text(
            "# Inbox\n\n" + entry("The inbox is first", ONE, "The inbox opens on the request."),
            encoding="utf-8",
        )
        (context / "chat.md").write_text(
            "# Chat\n\n" + entry("The chat list wraps names", TWO, "A name wraps as a whole word."),
            encoding="utf-8",
        )
        for name in vcm.FAMILIES:
            path = context / f"{name}.md"
            if not path.exists():
                path.write_text(f"# {name}\n", encoding="utf-8")
        return context

    def test_this_repository_maps_every_moved_entry(self) -> None:
        entries = vcm.load()
        table = split.load_table()
        self.assertEqual(len(entries), len(table))
        self.assertEqual({entry.id for entry in entries}, {entry_id for entry_id, _ in table})
        files = {entry.file for entry in entries}
        self.assertEqual(files, {f"{name}.md" for name in vcm.FAMILIES})
        inbox = vcm.resolve(entries, "a8f4ac34")
        self.assertEqual(len(inbox), 1)
        self.assertEqual(inbox[0].file, "inbox.md")

    def test_a_hunk_names_the_entry_and_a_new_id_beside_it(self) -> None:
        entries = vcm.load(self.tree())
        hunk = (
            "@@ -10,3 +10,8 @@\n"
            " The inbox opens on the request.\n"
            "+\n"
            "+## A further rule\n"
            "+\n"
            f"+**Id:** {NEW}\n"
        )
        rows = vcm.match_hunk(hunk, entries)
        self.assertEqual(rows[0][0], ONE)
        self.assertEqual(rows[0][1], "inbox.md")
        self.assertEqual(rows[1][0], NEW)
        self.assertEqual(rows[1][1], "new")
        self.assertIn(ONE, rows[1][2])
        self.assertIn("inbox.md", rows[1][2])

    def test_a_shared_field_line_matches_no_entry(self) -> None:
        entries = vcm.load(self.tree())
        self.assertEqual(vcm.match_hunk("**Status:** active\n", entries), [])

    def test_cli_prints_one_id(self) -> None:
        entries = vcm.load()
        target = entries[0]
        out = io.StringIO()
        with redirect_stdout(out):
            code = vcm.main([target.id])
        self.assertEqual(code, 0)
        self.assertTrue(out.getvalue().startswith(f"{target.id}\t{target.file}\t"))

    def test_zero_context_hunk_uses_the_old_line_number(self) -> None:
        entries = vcm.load()
        spans = vcm.source_spans(entries, vcm.source_order())
        hunk = "@@ -567 +567 @@\n-place.\n+one place.\n"
        rows = vcm.match_hunk(hunk, entries, spans)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][0], "561b77f6-2a12-4352-aa50-36a8aa773fbe")
        self.assertEqual(rows[0][1], "account.md")

    def test_new_id_before_a_mapped_neighbour_names_it(self) -> None:
        entries = vcm.load()
        hunk = (
            f"**Id:** {NEW}\n"
            "\n"
            "## The inbox is the first screen; board, agents, organisation and chat follow in that order\n"
        )
        rows = vcm.match_hunk(hunk, entries)
        self.assertEqual(rows[0][0], NEW)
        self.assertEqual(rows[0][1], "new")
        self.assertIn("beside a8f4ac34-b7be-47f0-aaec-dc494e6c2080 in inbox.md", rows[0][2])

    def test_cli_unknown_id(self) -> None:
        out = io.StringIO()
        with redirect_stdout(out):
            code = vcm.main([NEW])
        self.assertEqual(code, 1)
        self.assertIn("not in the views.md map", out.getvalue())
