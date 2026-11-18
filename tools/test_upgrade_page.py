"""Tests for upgrade_page.py on a temporary tree; no network, no git."""

from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import upgrade_page as u

ROOT = Path(__file__).resolve().parent.parent
FULL = "# Upgrading to 0.1.0a9\n\n" + "".join(f"## {s}\n\nNothing.\n\n" for s in u.SECTIONS)


class Tree:
    """A repository root with hub/pyproject.toml, CHANGELOG.md and maybe a page."""

    def __init__(self, version="0.1.0a9", folded=True, page=FULL):
        self.dir = tempfile.TemporaryDirectory()
        self.root = Path(self.dir.name)
        (self.root / "hub").mkdir()
        (self.root / "hub" / "pyproject.toml").write_text(
            f'[project]\nname = "maity-hub"\nversion = "{version}"\n', encoding="utf-8"
        )
        sections = f"## [{version}] - 2026-11-15\n\n### Added\n\n- x\n" if folded else ""
        (self.root / "CHANGELOG.md").write_text(
            f"# Changelog\n\n## [Unreleased]\n\n{sections}\n## [0.1.0a1] - 2026-10-01\n",
            encoding="utf-8",
        )
        if page is not None:
            (self.root / "docs" / "upgrade").mkdir(parents=True)
            (self.root / "docs" / "upgrade" / f"{version}.md").write_text(page, encoding="utf-8")

    def __enter__(self):
        return self.root

    def __exit__(self, *exc):
        self.dir.cleanup()


def run_main(root, *argv):
    out = io.StringIO()
    with mock.patch.object(u, "ROOT", root), contextlib.redirect_stdout(out):
        code = u.main(["check", *argv])
    return code, out.getvalue()


class Problems(unittest.TestCase):
    def test_a_complete_page_passes(self):
        with Tree() as root:
            self.assertEqual(u.problems(root, "0.1.0a9"), [])

    def test_a_missing_page_is_named(self):
        with Tree(page=None) as root:
            (found,) = u.problems(root, "0.1.0a9")
            self.assertIn("docs/upgrade/0.1.0a9.md is missing", found)

    def test_a_missing_section_is_named(self):
        page = FULL.replace("## What cannot be undone\n\nNothing.\n\n", "")
        with Tree(page=page) as root:
            (found,) = u.problems(root, "0.1.0a9")
            self.assertIn("## What cannot be undone", found)

    def test_sections_out_of_order_fail(self):
        first, second = u.SECTIONS[0], u.SECTIONS[1]
        page = FULL.replace(f"## {first}", "## TMP").replace(f"## {second}", f"## {first}")
        page = page.replace("## TMP", f"## {second}")
        with Tree(page=page) as root:
            (found,) = u.problems(root, "0.1.0a9")
            self.assertIn("in this order", found)

    def test_an_empty_section_fails(self):
        page = FULL.replace("## The way back\n\nNothing.\n", "## The way back\n\n")
        with Tree(page=page) as root:
            (found,) = u.problems(root, "0.1.0a9")
            self.assertIn("'## The way back' is empty", found)

    def test_a_heading_inside_a_code_block_does_not_count(self):
        page = FULL.replace("## The way back\n\nNothing.\n", "```\n## The way back\n```\n")
        with Tree(page=page) as root:
            (found,) = u.problems(root, "0.1.0a9")
            self.assertIn("## The way back", found)

    def test_an_empty_code_block_is_no_text(self):
        page = FULL.replace("## The way back\n\nNothing.\n", "## The way back\n\n```\n```\n")
        with Tree(page=page) as root:
            (found,) = u.problems(root, "0.1.0a9")
            self.assertIn("'## The way back' is empty", found)

    def test_a_code_block_with_text_counts(self):
        page = FULL.replace("## The way back\n\nNothing.\n", "## The way back\n\n```sh\nmaity-hub migrate\n```\n")
        with Tree(page=page) as root:
            self.assertEqual(u.problems(root, "0.1.0a9"), [])

    def test_extra_sections_are_allowed(self):
        page = FULL + "## Notes\n\nMore.\n"
        with Tree(page=page) as root:
            self.assertEqual(u.problems(root, "0.1.0a9"), [])


class Check(unittest.TestCase):
    def test_nothing_is_asked_before_the_fold(self):
        with Tree(folded=False, page=None) as root:
            code, out = run_main(root)
        self.assertEqual(code, 0)
        self.assertIn("not folded", out)

    def test_after_the_fold_the_page_is_required(self):
        with Tree(page=None) as root:
            code, out = run_main(root)
        self.assertEqual(code, 1)
        self.assertIn("::error::docs/upgrade/0.1.0a9.md is missing", out)

    def test_after_the_fold_a_complete_page_passes(self):
        with Tree() as root:
            code, out = run_main(root)
        self.assertEqual(code, 0)
        self.assertIn("complete", out)

    def test_version_asks_regardless_of_the_changelog(self):
        with Tree(folded=False, page=None) as root:
            code, _ = run_main(root, "--version", "0.1.0a9")
        self.assertEqual(code, 1)


class Template(unittest.TestCase):
    def test_the_readme_template_names_the_sections_in_order(self):
        text = (ROOT / "docs" / "upgrade" / "README.md").read_text(encoding="utf-8")
        positions = [text.find(f"## {s}") for s in u.SECTIONS]
        self.assertNotIn(-1, positions)
        self.assertEqual(positions, sorted(positions))


if __name__ == "__main__":
    unittest.main()
