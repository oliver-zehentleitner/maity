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

    def __init__(self, version="0.1.0a9", folded=True, page=FULL, readme=None):
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
            if readme is None:
                readme = f"# Upgrade pages\n\n## Versions\n\n- [{version}]({version}.md)\n"
            (self.root / "docs" / "upgrade" / "README.md").write_text(readme, encoding="utf-8")

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

    def test_a_byte_order_mark_is_dropped(self):
        # With the mark read as text, the first heading is no heading and the section is missing.
        page = "".join(f"## {s}\n\nNothing.\n\n" for s in u.SECTIONS)
        with Tree() as root:
            (root / "docs" / "upgrade" / "0.1.0a9.md").write_bytes(b"\xef\xbb\xbf" + page.encode("utf-8"))
            self.assertEqual(u.problems(root, "0.1.0a9"), [])

    def test_a_byte_order_mark_before_a_fence_keeps_the_fence(self):
        # Seen as text, the first fence line would turn every later fence inside out.
        page = "```\n## What changes for users\n```\n\n" + FULL
        with Tree() as root:
            (root / "docs" / "upgrade" / "0.1.0a9.md").write_bytes(b"\xef\xbb\xbf" + page.encode("utf-8"))
            self.assertEqual(u.problems(root, "0.1.0a9"), [])

    def test_a_four_backtick_fence_holds_a_three_backtick_one(self):
        block = "````markdown\n```\n## The way back\n```\n````\n"
        page = FULL.replace("## The way back\n\nNothing.\n", block + "\n## The way back\n\nNothing.\n")
        with Tree(page=page) as root:
            self.assertEqual(u.problems(root, "0.1.0a9"), [])

    def test_a_four_backtick_fence_is_closed_only_by_four_or_more(self):
        # The ``` line inside does not close it, so the heading after it is still code.
        block = "````\n```\n## The way back\n"
        page = FULL.replace("## The way back\n\nNothing.\n", block)
        with Tree(page=page) as root:
            (found,) = u.problems(root, "0.1.0a9")
            self.assertIn("lacks the section(s): ## The way back", found)

    def test_a_longer_closing_run_closes(self):
        page = FULL.replace("## The way back\n\nNothing.\n", "````\nx\n``````\n\n## The way back\n\nNothing.\n")
        with Tree(page=page) as root:
            self.assertEqual(u.problems(root, "0.1.0a9"), [])

    def test_a_tilde_fence_hides_a_heading(self):
        page = FULL.replace("## The way back\n\nNothing.\n", "~~~\n## The way back\n~~~\n")
        with Tree(page=page) as root:
            (found,) = u.problems(root, "0.1.0a9")
            self.assertIn("lacks the section(s): ## The way back", found)

    def test_backticks_do_not_close_a_tilde_fence(self):
        block = "~~~markdown\n```\n## The way back\n```\n~~~\n"
        page = FULL.replace("## The way back\n\nNothing.\n", block + "\n## The way back\n\nNothing.\n")
        with Tree(page=page) as root:
            self.assertEqual(u.problems(root, "0.1.0a9"), [])

    def test_an_empty_tilde_block_is_no_text(self):
        page = FULL.replace("## The way back\n\nNothing.\n", "## The way back\n\n~~~\n~~~\n")
        with Tree(page=page) as root:
            (found,) = u.problems(root, "0.1.0a9")
            self.assertIn("'## The way back' is empty", found)

    def test_an_indented_fence_counts_up_to_three_spaces(self):
        page = FULL.replace("## The way back\n\nNothing.\n", "   ```\n## The way back\n   ```\n")
        with Tree(page=page) as root:
            (found,) = u.problems(root, "0.1.0a9")
            self.assertIn("lacks the section(s): ## The way back", found)

    def test_a_fence_indented_four_spaces_is_indented_code_and_text(self):
        # CommonMark: four spaces make an indented code block, not a fence; its line shows.
        page = FULL.replace("## The way back\n\nNothing.\n", "## The way back\n\n    ```\n")
        with Tree(page=page) as root:
            self.assertEqual(u.problems(root, "0.1.0a9"), [])

    def test_a_backtick_info_string_with_a_backtick_opens_no_fence(self):
        # "``` a`b" is inline code in a paragraph (CommonMark), so the heading after it counts.
        page = FULL.replace("## The way back\n\nNothing.\n", "``` a`b\n\n## The way back\n\nNothing.\n")
        with Tree(page=page) as root:
            self.assertEqual(u.problems(root, "0.1.0a9"), [])

    def test_a_heading_indented_up_to_three_spaces_counts(self):
        page = FULL.replace("## The way back", "   ## The way back")
        with Tree(page=page) as root:
            self.assertEqual(u.problems(root, "0.1.0a9"), [])

    def test_a_section_of_only_a_comment_is_empty(self):
        page = FULL.replace("## The way back\n\nNothing.\n", "## The way back\n\n<!-- Nothing yet. -->\n")
        with Tree(page=page) as root:
            (found,) = u.problems(root, "0.1.0a9")
            self.assertIn("'## The way back' is empty", found)

    def test_a_section_of_only_multi_line_comments_is_empty(self):
        body = "## The way back\n\n<!--\nTODO: the dump\n-->\n\n  <!-- two --> <!-- three -->\n"
        page = FULL.replace("## The way back\n\nNothing.\n", body)
        with Tree(page=page) as root:
            (found,) = u.problems(root, "0.1.0a9")
            self.assertIn("'## The way back' is empty", found)

    def test_an_unclosed_comment_is_no_text(self):
        page = FULL.replace("## The way back\n\nNothing.\n", "## The way back\n\n<!-- Nothing.\n")
        with Tree(page=page) as root:
            (found,) = u.problems(root, "0.1.0a9")
            self.assertIn("'## The way back' is empty", found)

    def test_text_beside_a_comment_counts(self):
        page = FULL.replace("## The way back\n\nNothing.\n", "## The way back\n\n<!-- checked -->\nNothing.\n")
        with Tree(page=page) as root:
            self.assertEqual(u.problems(root, "0.1.0a9"), [])

    def test_a_comment_in_a_code_block_is_text(self):
        page = FULL.replace("## The way back\n\nNothing.\n", "## The way back\n\n```html\n<!-- shown -->\n```\n")
        with Tree(page=page) as root:
            self.assertEqual(u.problems(root, "0.1.0a9"), [])

    def test_a_heading_inside_a_comment_does_not_count(self):
        page = FULL.replace("## The way back\n\nNothing.\n", "<!--\n## The way back\nNothing.\n-->\n")
        with Tree(page=page) as root:
            (found,) = u.problems(root, "0.1.0a9")
            self.assertIn("lacks the section(s): ## The way back", found)


class Listing(unittest.TestCase):
    def test_a_linked_page_is_listed(self):
        with Tree() as root:
            self.assertEqual(u.unlisted(root), [])

    def test_a_page_the_readme_does_not_link_is_named(self):
        with Tree(readme="# Upgrade pages\n\nNo list.\n") as root:
            (found,) = u.unlisted(root)
        self.assertIn("docs/upgrade/README.md does not link 0.1.0a9.md", found)

    def test_check_refuses_an_unlisted_page_before_the_fold_too(self):
        with Tree(folded=False, readme="# Upgrade pages\n") as root:
            code, out = run_main(root)
        self.assertEqual(code, 1)
        self.assertIn("::error::docs/upgrade/README.md does not link 0.1.0a9.md", out)

    def test_no_pages_need_no_readme(self):
        with Tree(page=None) as root:
            self.assertEqual(u.unlisted(root), [])


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

    def test_the_readme_links_every_version_page(self):
        self.assertEqual(u.unlisted(ROOT), [])

    def test_every_version_page_in_the_repository_is_complete(self):
        # Each page passed when its release was folded; the parser's rules must not refuse it later.
        for page in sorted((ROOT / "docs" / "upgrade").glob("*.md")):
            if page.name != "README.md":
                with self.subTest(page=page.name):
                    self.assertEqual(u.problems(ROOT, page.stem), [])

    def test_the_repository_passes_check_as_ci_runs_it(self):
        code, out = run_main(ROOT)
        self.assertEqual(code, 0, out)


if __name__ == "__main__":
    unittest.main()
