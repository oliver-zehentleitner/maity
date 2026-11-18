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

    def fences(self, page, *numbers):
        """The page is refused as a whole, with one error per indented fence line, by number."""
        with Tree(page=page) as root:
            self.assertEqual(
                u.problems(root, "0.1.0a9"),
                [f"docs/upgrade/0.1.0a9.md:{n}: write code fences at the start of the line" for n in numbers],
            )

    def test_an_indented_fence_makes_the_page_refused(self):
        # Lines 1-18 are the title and four sections; the fifth starts at line 19.
        for pad in (" ", "  ", "   "):
            for run in ("```", "~~~", "````", "```sh"):
                with self.subTest(pad=pad, run=run):
                    block = f"## The way back\n\n{pad}{run}\nmaity-hub migrate\n{run[:3]}\n"
                    self.fences(FULL.replace("## The way back\n\nNothing.\n", block), 21)

    def test_an_indented_fence_is_refused_wherever_it_stands(self):
        # A plain line scan: inside a list item, a column-0 fence or a comment block too.
        for block, number in (
            ("- a\n\n  ```\n  x\n", 21),
            ("```\n  ~~~\n```\n", 20),
            ("````\n  ```\n````\n", 20),
            ("<!--\n  ```\n-->\n", 20),
        ):
            with self.subTest(block=block):
                page = FULL.replace("## The way back\n\nNothing.\n", block + "\n## The way back\n\nNothing.\n")
                self.fences(page, number)

    # A1435: the round-4 indent-closing rule accepted these; CommonMark reads them otherwise.
    def test_an_empty_block_opened_indented_and_closed_at_column_0_is_refused(self):
        for block in ("  ```\n```\n", "   ~~~\n~~~\n"):
            with self.subTest(block=block):
                self.fences(FULL.replace("## The way back\n\nNothing.\n", "## The way back\n\n" + block), 21)

    def test_a_duplicate_heading_after_an_indented_fence_is_refused(self):
        self.fences(FULL + "  ```\nx\n```\n## The way back\n\nNothing.\n", 23)

    def test_a_heading_hidden_by_a_reopened_fence_is_refused(self):
        block = "## What cannot be undone\n\nNothing.\n  ```\nx\n```\n  ```\n"
        self.fences(FULL.replace("## What cannot be undone\n\nNothing.\n", block), 18, 21)

    def test_check_names_the_indented_fence(self):
        page = FULL.replace("## The way back\n\nNothing.\n", "## The way back\n\n  ```\n```\n")
        with Tree(page=page) as root:
            code, out = run_main(root)
        self.assertEqual(code, 1)
        self.assertIn("::error::docs/upgrade/0.1.0a9.md:21: write code fences at the start of the line", out)
        self.assertNotIn("complete", out)

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

    def test_a_comment_indented_four_spaces_is_code_and_text(self):
        # CommonMark shows "    <!-- x -->" as a code block; the fenced control is the test above.
        page = FULL.replace("## The way back\n\nNothing.\n", "## The way back\n\n    <!-- x -->\n")
        with Tree(page=page) as root:
            self.assertEqual(u.problems(root, "0.1.0a9"), [])

    def test_a_comment_indented_by_a_tab_is_code_and_text(self):
        page = FULL.replace("## The way back\n\nNothing.\n", "## The way back\n\n\t<!-- x -->\n")
        with Tree(page=page) as root:
            self.assertEqual(u.problems(root, "0.1.0a9"), [])

    def test_an_indented_unclosed_comment_hides_no_text_after_it(self):
        # "    <!-- example" is code, so it opens no comment block that would swallow "Nothing.".
        page = FULL.replace("## The way back\n\nNothing.\n", "## The way back\n\n    <!-- example\n\nNothing.\n")
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
        self.assertIn('add the list line "- [0.1.0a9](0.1.0a9.md)" to docs/upgrade/README.md', found)

    def refused(self, readme):
        with Tree(readme=readme) as root:
            (found,) = u.unlisted(root)
        self.assertIn("does not link 0.1.0a9.md", found)

    def accepted(self, readme):
        with Tree(readme=readme) as root:
            self.assertEqual(u.unlisted(root), [])

    def test_a_link_inside_a_comment_does_not_count(self):
        self.refused("# Upgrade pages\n\n<!-- - [0.1.0a9](0.1.0a9.md) -->\n")
        self.refused("# Upgrade pages\n\n<!--\n- [0.1.0a9](0.1.0a9.md)\n-->\n")

    def test_a_link_inside_a_fenced_example_does_not_count(self):
        self.refused("# Upgrade pages\n\n```markdown\n- [0.1.0a9](0.1.0a9.md)\n```\n")

    def test_a_link_inside_an_indented_example_does_not_count(self):
        self.refused("# Upgrade pages\n\n    - [0.1.0a9](0.1.0a9.md)\n")

    def test_a_link_inside_a_code_span_does_not_count(self):
        self.refused("# Upgrade pages\n\nWrite `- [0.1.0a9](0.1.0a9.md)`.\n")

    def test_a_reference_definition_alone_does_not_count(self):
        self.refused("# Upgrade pages\n\n[a9]: 0.1.0a9.md\n")

    def test_a_dot_slash_link_counts(self):
        self.accepted("# Upgrade pages\n\n- [0.1.0a9](./0.1.0a9.md)\n")

    def test_a_link_with_a_fragment_or_angle_brackets_counts(self):
        self.accepted("# Upgrade pages\n\n- [0.1.0a9](0.1.0a9.md#x)\n")
        self.accepted("# Upgrade pages\n\n- [0.1.0a9](<./0.1.0a9.md#x>)\n")

    def test_a_star_list_line_with_trailing_text_counts(self):
        self.accepted("# Upgrade pages\n\n* [0.1.0a9](0.1.0a9.md) (skip it)\n")

    def fences(self, readme, *numbers):
        """The README is refused as a whole, with one error per indented fence line, by number."""
        with Tree(readme=readme) as root:
            self.assertEqual(
                u.unlisted(root),
                [f"docs/upgrade/README.md:{n}: write code fences at the start of the line" for n in numbers],
            )

    # A1420: a list line starts at column 0, so a list item's fence or comment cannot fake one;
    # a fence indented inside a list item makes the README refused as a whole.
    def test_a_list_line_inside_a_list_items_fence_does_not_count(self):
        self.fences("# Upgrade pages\n\n- ```\n  - [0.1.0a9](0.1.0a9.md)\n  ```\n", 5)
        self.fences("# Upgrade pages\n\n1. ~~~\n   - [0.1.0a9](0.1.0a9.md)\n   ~~~\n", 5)

    def test_a_list_line_inside_a_list_items_comment_does_not_count(self):
        self.refused("# Upgrade pages\n\n- <!--\n  - [0.1.0a9](0.1.0a9.md)\n  -->\n")

    def test_a_list_line_inside_a_code_block_after_a_list_items_fence_does_not_count(self):
        # CommonMark: the "```" at column 0 ends the list item and opens a code block that runs
        # to the end. Here: the fence indented in the list item refuses the README.
        self.fences("# Upgrade pages\n\n- a\n  ```\n```\n- [0.1.0a9](0.1.0a9.md)\n", 4)

    # A1435: the round-4 indent-closing rule closed "  ```" on a later "  ```" (CommonMark opens a
    # new block there, hiding the list line); the indented fence now refuses the README.
    def test_a_list_line_after_a_reopened_indented_fence_is_refused(self):
        for block, numbers in (
            ("  ```\n```\n  ```\n", (5, 7)),
            ("   ~~~\nx\n~~~\n   ~~~\n", (5, 8)),
            (" ```\n```\n   ```\n", (5, 7)),
        ):
            with self.subTest(block=block):
                self.fences(f"# Upgrade pages\n\n## Versions\n\n{block}- [0.1.0a9](0.1.0a9.md)\n", *numbers)

    def test_check_names_the_indented_fence_in_the_readme(self):
        with Tree(readme="# Upgrade pages\n\n  ```\n```\n- [0.1.0a9](0.1.0a9.md)\n") as root:
            code, out = run_main(root)
        self.assertEqual(code, 1)
        self.assertIn("::error::docs/upgrade/README.md:3: write code fences at the start of the line", out)

    def test_an_indented_list_line_does_not_count(self):
        for pad in (" ", "  ", "   "):
            for bullet in ("-", "*"):
                with self.subTest(pad=pad, bullet=bullet):
                    self.refused(f"# Upgrade pages\n\n{pad}{bullet} [0.1.0a9](0.1.0a9.md)\n")

    def test_a_list_line_after_a_list_items_fence_is_refused(self):
        # Deliberate fail-closed edge: CommonMark ends the fence with the list item and shows
        # the link, but the fence indented in the list item refuses the README.
        self.fences("# Upgrade pages\n\n- ```\n  - [0.1.0a9](0.1.0a9.md)\n  ```\n- [0.1.0a9](0.1.0a9.md)\n", 5)

    def test_a_list_line_after_a_list_items_comment_is_refused(self):
        # Deliberate fail-closed edge: "  <!--" opens a comment block here that runs to the end;
        # CommonMark ends it with the list item and shows the link.
        self.refused("# Upgrade pages\n\n- a\n  <!--\n- [0.1.0a9](0.1.0a9.md)\n")

    # Forms a fuller recognizer accepted (9ecab5fe), refused by the list-line rule.
    def test_a_reference_link_does_not_count(self):
        self.refused("# Upgrade pages\n\n- [0.1.0a9][A9]\n\n[a9]: 0.1.0a9.md\n")

    def test_a_link_on_a_paragraph_continuation_line_does_not_count(self):
        self.refused("# Upgrade pages\n\nThe pages:\n    [0.1.0a9](0.1.0a9.md)\n")

    def test_a_link_inside_a_paragraph_does_not_count(self):
        self.refused("# Upgrade pages\n\nSee [0.1.0a9](0.1.0a9.md) for the steps.\n")

    def test_a_link_with_a_title_does_not_count(self):
        self.refused('# Upgrade pages\n\n- [0.1.0a9](0.1.0a9.md "title")\n')

    # A1413: what the fuller recognizer counted although the rendered README does not link the page.
    def test_a_reference_to_another_label_does_not_count(self):
        self.refused("# Upgrade pages\n\n- [0.1.0a9][elsewhere]\n\n[0.1.0a9]: 0.1.0a9.md\n[elsewhere]: other.md\n")

    def test_an_image_does_not_count(self):
        self.refused("# Upgrade pages\n\n![picture][a9]\n\n[a9]: 0.1.0a9.md\n")
        self.refused("# Upgrade pages\n\n- ![0.1.0a9](0.1.0a9.md)\n")

    def test_a_code_span_between_text_and_destination_does_not_count(self):
        self.refused("# Upgrade pages\n\n- [0.1.0a9]`x`(0.1.0a9.md)\n")

    def test_a_comment_between_text_and_destination_does_not_count(self):
        self.refused("# Upgrade pages\n\n- [0.1.0a9]<!-- x -->(0.1.0a9.md)\n")

    # A1421 nit-1: a raw HTML tag or an autolink opened in the link text spans the destination,
    # so CommonMark renders no link; "<" in the link text is refused.
    def test_a_tag_or_autolink_opened_in_the_link_text_does_not_count(self):
        for line in (
            '- [x <span title="](0.1.0a9.md)">](other.md)',
            '- [x <span title="](0.1.0a9.md)">',
            "- [x <http://a](0.1.0a9.md)>",
            "- [x <http://e.org/](0.1.0a9.md)> y",
        ):
            with self.subTest(line=line):
                self.refused(f"# Upgrade pages\n\n{line}\n")

    def test_an_escaped_bracket_does_not_count(self):
        self.refused("# Upgrade pages\n\n- \\[0.1.0a9](0.1.0a9.md)\n")
        self.refused("# Upgrade pages\n\n- [0.1.0a9\\](0.1.0a9.md)\n")

    def test_a_comment_opener_in_a_code_span_hides_no_later_list_line(self):
        self.accepted("# Upgrade pages\n\nWrite `<!--` to open a comment.\n\n- [0.1.0a9](0.1.0a9.md)\n")

    # A1414: an opener inside a line opens no comment block, so the list lines after it count.
    def test_an_unclosed_comment_inside_prose_hides_no_later_list_line(self):
        self.accepted("# Upgrade pages\n\nText <!-- not closed\n\n- [0.1.0a9](0.1.0a9.md)\n")

    def test_the_real_readme_with_a_code_span_opener_still_links_every_page(self):
        text = (ROOT / "docs" / "upgrade" / "README.md").read_text(encoding="utf-8")
        anchor = "on its own and how to go back.\n"
        self.assertIn(anchor, text)
        probe = text.replace(anchor, anchor + "A section that holds only a `<!--` comment counts as empty.\n")
        self.assertEqual(u.links(probe), u.links(text))
        self.assertIn("0.1.0a9.md", u.links(probe))

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
