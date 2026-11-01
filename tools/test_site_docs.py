"""Tests for tools/site_docs.py.

Needs `markdown` and `PyYAML` (skipped without them):
    python3 -m unittest discover -s tools -p 'test_*.py'
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    import site_docs
except ImportError:  # markdown or PyYAML missing
    site_docs = None


@unittest.skipIf(site_docs is None, "markdown and PyYAML are needed")
class SiteDocsTest(unittest.TestCase):
    def test_urls(self):
        self.assertEqual(site_docs.url_for("docs/README.md"), "/docs/")
        self.assertEqual(site_docs.url_for("docs/agents.md"), "/docs/agents/")
        self.assertEqual(site_docs.url_for("docs/install/README.md"), "/docs/install/")
        self.assertEqual(site_docs.url_for("docs/install/quickstart.md"), "/docs/install/quickstart/")
        self.assertEqual(site_docs.url_for("cli/README.md"), "/docs/cli/")

    def test_slugs_follow_github(self):
        self.assertEqual(site_docs.slugify("6.23 The Keep the Why commitment"), "623-the-keep-the-why-commitment")
        self.assertEqual(site_docs.slugify("4. <code>GET /help</code>"), "4-get-help")
        self.assertEqual(site_docs.slugify("Members and Organisation"), "members-and-organisation")

    def test_split_ignores_headings_in_code(self):
        intro, sections = site_docs.split_sections("# T\n\nintro\n\n## A\n\n```md\n## not a section\n```\n\n## B\n")
        self.assertIn("intro", intro)
        self.assertEqual([s.splitlines()[0] for s in sections], ["## A", "## B"])

    def test_duplicate_headings_are_numbered_like_github(self):
        _, toc = site_docs.render("## Example\n\n## Example\n", {})
        self.assertEqual([a for _, a, _ in toc], ["example", "example-1"])

    def test_alerts_tables_and_links(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, site = Path(tmp) / "repo", Path(tmp) / "site"
            (repo / "docs").mkdir(parents=True)
            (repo / "docs/a.md").write_text(
                "# A\n\nLead.\n\n> [!NOTE]\n> Careful.\n\n| x |\n|---|\n| 1 |\n\n"
                "[b](b.md#two) [api](api.md#2-second) [ctx](../context/index.md) [web](https://example.org)\n"
            )
            (repo / "docs/b.md").write_text("# B\n\n## One\n\n## Two\n")
            (repo / "docs/api.md").write_text("# API\n\nThe contract.\n\n## 1. First\n\ntext\n\n## 2. Second\n\ntext\n")
            (repo / "docs/nav.yml").write_text(
                "- group: G\n  pages:\n    - {src: docs/a.md, title: A}\n    - {src: docs/b.md, title: B}\n"
                "    - {src: docs/api.md, title: API, split: true}\n"
            )
            self.assertEqual(site_docs.main([str(site), "--repo", str(repo)]), 0)
            page = (site / "docs/a/index.html").read_text()
            self.assertIn('class="alert alert-note"', page)
            self.assertIn('<div class="table"><table>', page)
            self.assertIn('href="/docs/b/#two"', page)
            self.assertIn('href="/docs/api/2-second/#2-second"', page)
            self.assertIn('href="https://github.com/oliver-zehentleitner/maity/blob/main/context/index.md"', page)
            self.assertIn('href="https://example.org"', page)
            self.assertIn('<meta name="description" content="Lead.">', page)
            self.assertTrue((site / "docs/api/1-first/index.html").is_file())
            self.assertIn('href="/docs/api/1-first/"', (site / "docs/api/index.html").read_text())
            self.assertTrue((site / "docs/_assets/search.json").is_file())


    def test_the_real_nav_builds_and_hides_section_14(self):
        repo = Path(__file__).resolve().parent.parent
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(site_docs.main([tmp, "--repo", str(repo)]), 0)
            out = Path(tmp) / "docs"
            self.assertTrue((out / "api" / "index.html").is_file())
            self.assertFalse(list((out / "api").glob("14-*")))
            self.assertNotIn("/docs/api/14-", (out / "_assets" / "search.json").read_text("utf-8"))
            self.assertIn('href="/docs/api/', (out / "cli" / "index.html").read_text("utf-8"))


if __name__ == "__main__":
    unittest.main()
