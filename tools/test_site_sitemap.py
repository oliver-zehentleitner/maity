"""Tests for tools/site_sitemap.py.

Standard library only:
    python3 -m unittest discover -s tools -p 'test_*.py'
"""

from __future__ import annotations

import contextlib
import io
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import site_sitemap  # noqa: E402

NS = {"s": site_sitemap.NAMESPACE}


def make_site(root: Path) -> Path:
    site = root / "site"
    for name in (
        "index.html",
        "install/index.html",
        "guide/start.html",
        "keep-the-why-dashboard/index.html",
        "keep-the-why-dashboard/hub/index.html",
        ".hidden/page.html",
        "brand/loader.html",
    ):
        path = site / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("<!doctype html>", encoding="utf-8")
    (site / "brand" / "logo.svg").write_text("<svg/>", encoding="utf-8")
    (site / "agents.md").write_text("# not a page", encoding="utf-8")
    return site


class SitemapTests(unittest.TestCase):
    def test_every_html_page_but_the_dashboard_the_brand_files_and_hidden_ones_is_listed_sorted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            found = site_sitemap.pages(make_site(Path(tmp)))
        self.assertEqual(found, ["guide/start.html", "index.html", "install/index.html"])

    def test_a_folders_index_is_the_folders_address(self) -> None:
        url = site_sitemap.url_of
        self.assertEqual(url("https://maity.dev", "index.html"), "https://maity.dev/")
        self.assertEqual(url("https://maity.dev/", "install/index.html"), "https://maity.dev/install/")
        self.assertEqual(url("https://maity.dev", "guide/start.html"), "https://maity.dev/guide/start.html")

    def test_the_sitemap_is_well_formed_with_absolute_https_urls(self) -> None:
        text = site_sitemap.sitemap(
            "https://maity.dev", ["guide/a&b.html", "index.html", "install/index.html"]
        )
        root = ET.fromstring(text)
        locs = [e.text for e in root.findall("s:url/s:loc", NS)]
        self.assertEqual(
            locs,
            [
                "https://maity.dev/guide/a&b.html",
                "https://maity.dev/",
                "https://maity.dev/install/",
            ],
        )
        self.assertTrue(all(loc and loc.startswith("https://") for loc in locs))
        self.assertIn("&amp;", text)  # escaped in the file
        self.assertEqual(root.findall("s:url/s:lastmod", NS), [])  # no history, no date

    def test_robots_allows_everything_and_names_the_sitemap(self) -> None:
        self.assertEqual(
            site_sitemap.robots("https://maity.dev/"),
            "User-agent: *\nAllow: /\n\nSitemap: https://maity.dev/sitemap.xml\n",
        )

    def test_the_command_writes_both_files_into_the_site(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            site = make_site(Path(tmp))
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = site_sitemap.main([str(site)])
            self.assertEqual(code, 0)
            root = ET.fromstring((site / "sitemap.xml").read_text(encoding="utf-8"))
            self.assertEqual(len(root.findall("s:url", NS)), 3)
            self.assertIn("Sitemap: https://maity.dev/sitemap.xml", (site / "robots.txt").read_text())

    def test_an_empty_or_missing_site_is_an_error_and_writes_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            empty = Path(tmp) / "site"
            empty.mkdir()
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                self.assertEqual(site_sitemap.main([str(empty)]), 1)
                self.assertEqual(site_sitemap.main([str(Path(tmp) / "missing")]), 2)
            self.assertFalse((empty / "sitemap.xml").exists())


if __name__ == "__main__":
    unittest.main()
