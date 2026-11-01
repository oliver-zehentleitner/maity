#!/usr/bin/env python3
"""The docs pages of the project site, rendered from the Markdown in the repository.

    python3 tools/site_docs.py site [--nav docs/nav.yml] [--repo .]

Run by the pages workflow after `site/` is assembled and before the sitemap. Every page
listed in `docs/nav.yml` is rendered with one HTML template (`tools/site_docs/`) to
`site/docs/<path>/index.html`; `docs/README.md` becomes `/docs/` and `cli/README.md`
`/docs/cli/`. A page marked `split` gets one page per `##` section (the API contract). Links
between rendered pages point at their pages, every other link into the repository at GitHub.
The pages work without JavaScript; `docs.js` only adds the copy buttons and the search, from
`site/docs/_assets/search.json`. Needs `markdown` and `PyYAML`.
"""

from __future__ import annotations

import argparse
import html
import json
import posixpath
import re
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from string import Template

import markdown
import yaml

GITHUB = "https://github.com/oliver-zehentleitner/maity"
BASE = "/docs/"
ASSETS = Path(__file__).with_name("site_docs")
FONTS = Path("hub/src/maity_hub/landing_assets/fonts")
EXTENSIONS = ["tables", "fenced_code", "footnotes", "attr_list", "def_list", "md_in_html", "sane_lists"]
ALERTS = {"NOTE": "Note", "TIP": "Tip", "IMPORTANT": "Important", "WARNING": "Warning", "CAUTION": "Caution"}


@dataclass
class Page:
    src: str  # repository-relative Markdown file
    url: str  # site path, ending in "/"
    title: str  # navigation title
    heading: str = ""  # the page's own h1
    body: str = ""  # rendered HTML, links not yet rewritten
    toc: list[tuple[int, str, str]] = field(default_factory=list)  # (level, id, text)
    lead: str = ""
    hide: set[str] = field(default_factory=set)
    hidden: set[str] = field(default_factory=set)  # anchors of sections left out of a split page
    parent: str | None = None  # url of the split page this section belongs to
    children: list["Page"] = field(default_factory=list)


def url_for(src: str) -> str:
    """docs/README.md → /docs/, docs/install/quickstart.md → /docs/install/quickstart/,
    cli/README.md → /docs/cli/."""
    path = src.removeprefix("docs/").removesuffix(".md")
    if path.endswith("README"):
        path = path.removesuffix("README")
    path = path.strip("/")
    return BASE + (path + "/" if path else "")


def slugify(text: str) -> str:
    """GitHub's heading anchors, so that links written for GitHub keep working."""
    text = re.sub(r"<[^>]+>", "", html.unescape(text)).strip().lower()
    text = re.sub(r"[^\w\- ]", "", text)
    return text.replace(" ", "-")


def split_sections(text: str) -> tuple[str, list[str]]:
    """The intro before the first `## ` and each `## ` section, outside code fences."""
    parts, current, fence = [], [], None
    intro = None
    for line in text.splitlines(keepends=True):
        m = re.match(r"^(```+|~~~+)", line)
        if m:
            fence = None if fence and line.startswith(fence) else (fence or m.group(1))
        if fence is None and line.startswith("## "):
            if intro is None:
                intro = "".join(current)
            else:
                parts.append("".join(current))
            current = []
        current.append(line)
    if intro is None:
        return "".join(current), []
    parts.append("".join(current))
    return intro, parts


def render(text: str, seen: dict[str, int]) -> tuple[str, list[tuple[int, str, str]]]:
    """Markdown to HTML with GitHub anchors on h1–h4 (unique across `seen`), GitHub alerts,
    scrollable tables and anchor links; returns the HTML and its headings."""
    body = markdown.markdown(text, extensions=EXTENSIONS, output_format="html")
    headings: list[tuple[int, str, str]] = []

    def heading(m: re.Match) -> str:
        level, attrs, inner = int(m.group(1)), m.group(2), m.group(3)
        base = slugify(inner)
        n = seen.get(base, 0)
        seen[base] = n + 1
        anchor = base if n == 0 else f"{base}-{n}"
        headings.append((level, anchor, re.sub(r"<[^>]+>", "", inner)))
        link = f'<a class="anchor" href="#{anchor}" aria-label="Link to this section">#</a>' if level > 1 else ""
        return f'<h{level} id="{anchor}"{attrs}>{inner}{link}</h{level}>'

    body = re.sub(r"<h([1-4])((?: [^>]*)?)>(.*?)</h\1>", heading, body, flags=re.S)

    def alert(m: re.Match) -> str:
        kind = m.group(1)
        return f'<div class="alert alert-{kind.lower()}"><p class="alert-title">{ALERTS[kind]}</p><p>{m.group(2)}'

    body = re.sub(r"<blockquote>\s*<p>\[!(" + "|".join(ALERTS) + r")\]\s*(.*?)(?=</p>)", alert, body, flags=re.S)
    body = re.sub(r'(<div class="alert[^>]*>.*?)</blockquote>', r"\1</div>", body, flags=re.S)
    body = body.replace("<table>", '<div class="table"><table>').replace("</table>", "</table></div>")
    return body, headings


def first_paragraph(body: str) -> str:
    m = re.search(r"<p>(.*?)</p>", body, flags=re.S)
    if not m:
        return ""
    text = html.unescape(re.sub(r"<[^>]+>", "", m.group(1))).split("\n")
    text = " ".join(t.strip() for t in text).strip()
    return text if len(text) <= 160 else text[:157].rsplit(" ", 1)[0] + "…"


def build_pages(repo: Path, nav: list[dict]) -> tuple[list[Page], dict[str, Page]]:
    pages: list[Page] = []
    by_src: dict[str, Page] = {}
    for group in nav:
        for entry in group["pages"]:
            if "src" not in entry:
                continue
            src = entry["src"]
            text = (repo / src).read_text(encoding="utf-8")
            page = Page(src=src, url=url_for(src), title=entry["title"], hide=set(entry.get("hide", [])))
            seen: dict[str, int] = {}
            if entry.get("split"):
                intro, sections = split_sections(text)
                page.body, page.toc = render(intro, seen)
                for section in sections:
                    title = section.splitlines()[0][3:].strip()
                    child = Page(src=src, url="", title=title, parent=page.url)
                    child.body, child.toc = render(section, seen)
                    if child.toc[0][2] in page.hide:  # no page, no sitemap line, no search entry
                        page.hidden.update(anchor for _, anchor, _ in child.toc)
                        continue
                    child.url = f"{page.url}{child.toc[0][1]}/"
                    child.heading = child.toc[0][2]
                    child.hide = page.hide
                    page.children.append(child)
            else:
                page.body, page.toc = render(text, seen)
            page.heading = next((t for lvl, _, t in page.toc if lvl == 1), page.title)
            page.lead = first_paragraph(page.body)
            for child in page.children:
                child.lead = first_paragraph(child.body) or page.lead
            pages.append(page)
            pages.extend(page.children)
            by_src[src] = page
    return pages, by_src


def anchor_map(pages: list[Page]) -> dict[tuple[str, str], str]:
    """(source file, anchor) → the url of the page that carries the anchor."""
    found: dict[tuple[str, str], str] = {}
    for page in pages:
        for _, anchor, _ in page.toc:
            found.setdefault((page.src, anchor), page.url)
    return found


def rewrite_links(page: Page, by_src: dict[str, Page], anchors: dict[tuple[str, str], str]) -> str:
    """Relative links: to a rendered page → its page; anything else in the repository →
    GitHub. Absolute links and mail stay."""

    def target(href: str) -> str:
        href = html.unescape(href)
        # A README that PyPI shows too links the repository absolutely; on the site it is a link.
        if href.startswith(f"{GITHUB}/blob/main/"):
            href = "/".join([".."] * page.src.count("/") + [href.removeprefix(f"{GITHUB}/blob/main/")])
        if re.match(r"^[a-z][a-z0-9+.-]*:", href) or href.startswith("/"):
            return href
        path, _, frag = href.partition("#")
        src = posixpath.normpath(posixpath.join(posixpath.dirname(page.src), path)) if path else page.src
        if src in by_src and frag not in by_src[src].hidden:
            if frag:
                return anchors.get((src, frag), by_src[src].url) + "#" + frag
            return by_src[src].url
        kind = "tree" if path.endswith("/") or "." not in posixpath.basename(src) else "blob"
        return f"{GITHUB}/{kind}/main/{src}" + (f"#{frag}" if frag else "")

    return re.sub(r'href="([^"]*)"', lambda m: f'href="{html.escape(target(m.group(1)))}"', page.body)


def nav_html(nav: list[dict], by_src: dict[str, Page], current: Page) -> str:
    out = []
    for group in nav:
        out.append(f'<p class="nav-group">{html.escape(group["group"])}</p><ul>')
        for entry in group["pages"]:
            if "href" in entry:
                out.append(f'<li><a href="{html.escape(entry["href"])}">{html.escape(entry["title"])}</a></li>')
                continue
            page = by_src[entry["src"]]
            here = current is page or current.parent == page.url
            aria = ' aria-current="page"' if current is page else ""
            out.append(f'<li><a href="{page.url}"{aria}>{html.escape(page.title)}</a>')
            if page.children and here:
                out.append('<ul class="nav-sub">')
                for child in page.children:
                    aria = ' aria-current="page"' if current is child else ""
                    out.append(f'<li><a href="{child.url}"{aria}>{html.escape(child.heading)}</a></li>')
                out.append("</ul>")
            out.append("</li>")
        out.append("</ul>")
    return "\n".join(out)


def toc_html(page: Page) -> str:
    items = [(lvl, a, t) for lvl, a, t in page.toc if lvl in (2, 3) and t not in page.hide]
    if page.parent:
        items = [(lvl, a, t) for lvl, a, t in page.toc if lvl == 3]
    if len(items) < 2:
        return ""
    lis = "".join(f'<li class="toc-{lvl}"><a href="#{a}">{html.escape(t)}</a></li>' for lvl, a, t in items)
    return f'<nav class="toc" aria-label="On this page"><p>On this page</p><ul>{lis}</ul></nav>'


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("site", type=Path)
    parser.add_argument("--nav", type=Path, default=Path("docs/nav.yml"))
    parser.add_argument("--repo", type=Path, default=Path("."))
    args = parser.parse_args(argv)

    nav = yaml.safe_load((args.repo / args.nav).read_text(encoding="utf-8"))
    pages, by_src = build_pages(args.repo, nav)
    anchors = anchor_map(pages)
    template = Template((ASSETS / "template.html").read_text(encoding="utf-8"))
    out_root = args.site / "docs"
    search = []

    for page in pages:
        body = rewrite_links(page, by_src, anchors)
        if page.children:
            items = "".join(
                f'<li><a href="{c.url}">{html.escape(c.heading)}</a></li>' for c in page.children if c.heading not in page.hide
            )
            body += f'<h2 id="sections">Sections</h2><ol class="sections">{items}</ol>'
            page.toc.append((2, "sections", "Sections"))
        title = page.heading if page.heading != page.title else page.title
        if page.parent:
            title = f"{page.heading} · {by_src[page.src].title}"
        source = f"{GITHUB}/blob/main/{page.src}"
        if page.parent:
            source += "#" + page.toc[0][1]
        doc = template.substitute(
            title=html.escape(title),
            description=html.escape(page.lead, quote=True),
            canonical=f"https://maity.dev{page.url}",
            nav=nav_html(nav, by_src, page),
            toc=toc_html(page),
            content=body,
            source=html.escape(source),
        )
        target = out_root / page.url.removeprefix(BASE) / "index.html"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(doc, encoding="utf-8")
        hidden = False
        for level, anchor, text in page.toc:
            if level <= 2:
                hidden = text in page.hide  # what stands under a hidden heading goes with it
            if level <= 3 and not hidden:
                search.append({"t": text, "p": page.title if not page.parent else page.heading, "u": f"{page.url}#{anchor}" if level > 1 else page.url})

    assets = out_root / "_assets"
    assets.mkdir(parents=True, exist_ok=True)
    for name in ("docs.css", "docs.js"):
        shutil.copy(ASSETS / name, assets / name)
    fonts = args.repo / FONTS
    if fonts.is_dir():
        shutil.copytree(fonts, assets / "fonts", dirs_exist_ok=True)
    (assets / "search.json").write_text(json.dumps(search, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"site_docs: {len(pages)} pages in {out_root}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
