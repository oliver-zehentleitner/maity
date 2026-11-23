"""The skeletons of the public project, person and agent pages the hub stores (docs/api.md
§16.9), for the check that the dashboard draws the same structure over them (web/js/visitor.js).

Each page of web/tools/public-pages-fixture.json (an answer of `GET /public/pages/{path}`:
`path`, `kind`, `data`) is rendered by `public_design.page`, and the content of its `<main>`
reduced to its elements: `[tag, sorted classes, data-kind or null, [children]]`, every text and
every other attribute dropped. web/tools/public-skeletons.json holds them by kind. A change to
the design fails this test until the file is written again with one command, `make -C web
skeletons`, in the same pull request; the dashboard's side is compared with the same file.
"""

from __future__ import annotations

import json
import os
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from maity_hub import public_design, render

WEB = Path(__file__).resolve().parents[2] / "web"
WEB_TOOLS = WEB / "tools"
FIXTURE = WEB_TOOLS / "public-pages-fixture.json"
SKELETONS = WEB_TOOLS / "public-skeletons.json"
VOID = {"area", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "wbr"}


class Skeleton(HTMLParser):
    """The elements of a piece of HTML as nested lists, with the standard library's parser."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root: list[Any] = []
        self.open: list[list[Any]] = [self.root]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        found = dict(attrs)
        children: list[Any] = []
        self.open[-1].append(
            [tag, sorted((found.get("class") or "").split()), found.get("data-kind"), children]
        )
        if tag not in VOID:
            self.open.append(children)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        found = dict(attrs)
        self.open[-1].append(
            [tag, sorted((found.get("class") or "").split()), found.get("data-kind"), []]
        )

    def handle_endtag(self, tag: str) -> None:
        if tag not in VOID:
            assert len(self.open) > 1, f"</{tag}> closes nothing"
            self.open.pop()


def skeleton(html: str) -> list[Any]:
    parser = Skeleton()
    parser.feed(html)
    parser.close()
    assert len(parser.open) == 1, "an element is left open"
    return parser.root


def main_of(document: str) -> str:
    found = render.STORED_PAGE.search(document)
    assert found is not None, "not the shape page_document writes"
    return found["main"]


def test_the_skeletons_of_the_public_project_pages_are_recorded() -> None:
    pages = json.loads(FIXTURE.read_text())
    kinds = public_design.KINDS + public_design.PROFILE_KINDS
    assert sorted(p["kind"] for p in pages) == sorted(kinds), "one page per kind"
    recorded = {}
    for answer in pages:
        content = public_design.page(answer["kind"], answer["data"], answer["path"])
        document = render.page_document(
            lang="en", title="t", canonical="https://hub.example/", content=content, styled=False
        )
        recorded[answer["kind"]] = skeleton(main_of(document))
    text = json.dumps(recorded, indent=1, sort_keys=True) + "\n"
    if os.environ.get("MAITY_WRITE_SKELETONS"):
        SKELETONS.write_text(text)
    stale = (
        "the public pages' design changed: run `make -C web skeletons`,"
        " commit public-skeletons.json"
    )
    assert SKELETONS.exists() and SKELETONS.read_text() == text, stale


def test_the_words_are_the_dashboards() -> None:
    """Each fixed word of the stored pages is the dashboard's English word under the same key."""
    english = json.loads((WEB / "i18n" / "en.json").read_text(encoding="utf-8"))
    differ = {k: v for k, v in public_design.WORDS.items() if english.get(k) != v}
    assert not differ, differ
