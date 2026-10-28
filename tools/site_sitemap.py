#!/usr/bin/env python3
"""The project site's `sitemap.xml` and `robots.txt`, made from the files that are deployed.

    python3 tools/site_sitemap.py site [--base https://maity.dev] [--docs docs]

Run by the pages workflow after `site/` is assembled: every `.html` page under it is a URL,
except the Keep the Why dashboard (generated, with a page for every entry) and the brand
files (their `.html` is a fragment, not a page), and the
sitemap is written beside the pages with a `robots.txt` that names it. A page's last
modification is the date of the last commit that touched its source under `--docs`, when
the checkout has the history. Standard library only.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from xml.sax.saxutils import escape

# The generated dashboard (a page for every entry) and the brand files, whose `.html` is a
# fragment the web app inlines (`brand/loader.html`), are not pages to look up.
SKIPPED = ("keep-the-why-dashboard", "brand")
NAMESPACE = "http://www.sitemaps.org/schemas/sitemap/0.9"


def pages(site: Path, skipped: tuple[str, ...] = SKIPPED) -> list[str]:
    """The relative paths of the site's `.html` files, sorted, without the skipped folders
    and without anything hidden."""
    found = []
    for path in site.rglob("*.html"):
        relative = path.relative_to(site)
        if relative.parts[0] in skipped or any(p.startswith(".") for p in relative.parts):
            continue
        found.append(relative.as_posix())
    return sorted(found)


def url_of(base: str, page: str) -> str:
    """`index.html` is its folder's address: `https://maity.dev/` and `…/install/`."""
    base = base.rstrip("/")
    if page == "index.html":
        return f"{base}/"
    if page.endswith("/index.html"):
        return f"{base}/{page.removesuffix('index.html')}"
    return f"{base}/{page}"


def last_modified(docs: Path | None, page: str) -> str | None:
    """The date of the last commit that touched the page's source, or None."""
    if docs is None:
        return None
    try:
        done = subprocess.run(
            ["git", "log", "-1", "--format=%cs", "--", str(docs / page)],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    date = done.stdout.strip()
    return date if done.returncode == 0 and date else None


def sitemap(base: str, listed: list[str], docs: Path | None = None) -> str:
    lines = ['<?xml version="1.0" encoding="UTF-8"?>', f'<urlset xmlns="{NAMESPACE}">']
    for page in listed:
        lines.append("  <url>")
        lines.append(f"    <loc>{escape(url_of(base, page))}</loc>")
        date = last_modified(docs, page)
        if date:
            lines.append(f"    <lastmod>{date}</lastmod>")
        lines.append("  </url>")
    lines.append("</urlset>")
    return "\n".join(lines) + "\n"


def robots(base: str) -> str:
    return f"User-agent: *\nAllow: /\n\nSitemap: {base.rstrip('/')}/sitemap.xml\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("site", type=Path, help="the assembled site directory")
    parser.add_argument("--base", default="https://maity.dev", help="the site's address")
    parser.add_argument("--docs", type=Path, default=None, help="the pages' source, for dates")
    args = parser.parse_args(argv)
    if not args.site.is_dir():
        print(f"site_sitemap: {args.site} is not a directory", file=sys.stderr)
        return 2
    listed = pages(args.site)
    if not listed:
        print("site_sitemap: no .html page found; nothing to list", file=sys.stderr)
        return 1
    (args.site / "sitemap.xml").write_text(sitemap(args.base, listed, args.docs), encoding="utf-8")
    (args.site / "robots.txt").write_text(robots(args.base), encoding="utf-8")
    print(f"site_sitemap: {len(listed)} pages in {args.site / 'sitemap.xml'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
