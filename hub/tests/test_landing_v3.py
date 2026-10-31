"""docs/api.md §16.7, "Progressive enhancement": the landing page's own stylesheet, fonts and
script, the demo and opensource sections, the theme switch, and what a page without script
shows (tsk-m6ew67r1w3hc)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine

from maity_hub import landing_files, landing_stats
from tests import flow
from tests.conftest import ClientFactory
from tests.test_pages import ADMIN, SECTIONS, hero, publish

DEMO: dict[str, Any] = {
    "type": "demo",
    "enabled": True,
    "title": "See it work",
    "subline": "One question, one answer.",
    "terminal_lines": [
        {"kind": "cmd", "text": "maity wait"},
        {"kind": "out", "text": "no events"},
        {"kind": "note", "text": "an agent is asking"},
        {"kind": "out", "text": "request req-1"},
        {"kind": "out", "text": "answered: go"},
        {"kind": "cmd", "text": "maity say all done"},
    ],
    "inbox": {"from": "agent-b", "question": "Merge it?", "context": "CI is green."},
    "steps": [
        {"title": "Ask", "text": "The agent asks."},
        {"title": "Decide", "text": "You answer."},
        {"title": "Go on", "text": "It continues."},
    ],
}
OPENSOURCE: dict[str, Any] = {
    "type": "opensource",
    "enabled": True,
    "title": "Open source",
    "markdown": "Read the **code**.",
    "tiles": [{"title": "MIT", "text": "Free."}, {"title": "Self-hosted", "text": "Yours."}],
    "links": [{"label": "Source", "href": "https://example.com/src"}],
}
SCALES = {
    "type": "scales",
    "enabled": True,
    "title": "Scales",
    "items": [
        {"tag": "You", "title": "Solo", "text": "Alone.", "points": ["One", "Two"]},
        {"tag": "Team", "title": "Team", "text": "Together."},
    ],
}
BAND = {
    "type": "cta_band",
    "enabled": True,
    "title": "Start",
    "text": "Now.",
    "cta": {"label": "Go", "href": "/register"},
}


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    landing_stats.reset()
    landing_files.reset()
    return flow.human(make_client, migrated)


def page(owner: flow.Human, make_client: ClientFactory, *sections: dict[str, Any]) -> str:
    publish(owner, [hero(), *sections])
    return make_client().get("/").text


# --- the files --------------------------------------------------------------------------------


def test_the_stylesheet_is_cached_for_good_under_its_digest_and_repairs_a_stale_link(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    client = make_client()
    link = re.search(
        r'href="(/assets/landing/landing\.css\?v=[0-9a-f]{16})"', page(owner, make_client)
    )
    assert link is not None
    current = client.get(link.group(1))
    assert current.status_code == 200 and current.headers["content-type"].startswith("text/css")
    assert current.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert current.headers["x-content-type-options"] == "nosniff"
    stale = client.get("/assets/landing/landing.css?v=0000000000000000")
    assert stale.text == current.text and stale.headers["cache-control"] == "no-cache"
    assert client.get("/assets/landing/landing.css").headers["cache-control"] == "no-cache"
    assert "set-cookie" not in current.headers
    assert client.head(link.group(1)).status_code == 200
    # A revalidation of an unchanged file costs no body; another tag gets the file.
    etag = current.headers["etag"]
    same = client.get(link.group(1), headers={"If-None-Match": etag})
    assert same.status_code == 304 and same.content == b""
    assert same.headers["cache-control"] == current.headers["cache-control"]
    assert (
        client.get(
            "/assets/landing/landing.css", headers={"If-None-Match": f'W/{etag}, "x"'}
        ).status_code
        == 304
    )
    assert client.get(link.group(1), headers={"If-None-Match": '"other"'}).status_code == 200


def test_every_font_of_the_stylesheet_is_a_versioned_file_of_the_hub(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    client = make_client()
    css = client.get("/assets/landing/landing.css").text
    assert not re.search(r"\{font:[a-z0-9-]+\.woff2\}", css) and "font-display:swap" in css
    names = re.findall(r"url\((fonts/[a-z0-9-]+\.woff2\?v=[0-9a-f]{16})\)", css)
    assert len(names) == 9  # Space Grotesk 500/600/700, Inter 400–700, JetBrains Mono 400/500
    for name in names:
        font = client.get(f"/assets/landing/{name}")
        assert font.status_code == 200 and font.headers["content-type"] == "font/woff2"
        assert font.headers["cache-control"] == "public, max-age=31536000, immutable"
        assert font.content[:4] == b"wOF2"
    for licence in ("space-grotesk", "inter", "jetbrains-mono"):
        text = client.get(f"/assets/landing/fonts/OFL-{licence}.txt")
        assert text.status_code == 200 and "SIL Open Font License" in text.text


@pytest.mark.wheel
def test_the_files_travel_with_the_package(make_client: ClientFactory) -> None:
    """Whatever this runs from, a checkout or the installed wheel (CI's hub-wheel job), the
    hub has its landing files: the stylesheet, nine fonts and their licences, the pictures."""
    client = make_client()
    css = client.get("/assets/landing/landing.css")
    assert css.status_code == 200 and "@font-face" in css.text
    assert len(re.findall(r"url\(fonts/[a-z0-9-]+\.woff2\?v=", css.text)) == 9
    assert client.get("/assets/landing/fonts/OFL-inter.txt").status_code == 200
    for picture in ("hero-rings.svg", "band-loader.svg", "mark.svg"):
        assert landing_files.svg(picture).startswith("<svg")


def test_nothing_else_is_served_from_the_directory(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    client = make_client()
    for path in (
        "hero-rings.svg",
        "mark.svg",
        "../landing.py",
        "fonts/../landing.css/..",
        "fonts/missing.woff2",
        "fonts/",
        ".hidden",
    ):
        assert client.get(f"/assets/landing/{path}").status_code == 404, path


def test_the_script_is_loaded_with_defer_when_the_hub_has_one(
    owner: flow.Human,
    make_client: ClientFactory,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "assets"
    root.mkdir()
    (root / "landing.css").write_text("body{}", encoding="utf-8")
    monkeypatch.setattr(landing_files, "ROOT", root)
    landing_files.reset()
    assert "<script" not in page(owner, make_client)  # a hub without landing.js links none
    (root / "landing.js").write_text('"use strict";\n', encoding="utf-8")
    landing_files.reset()
    html = make_client().get("/").text
    assert re.search(
        r'<script src="/assets/landing/landing\.js\?v=[0-9a-f]{16}" defer></script>', html
    )
    script = make_client().get("/assets/landing/landing.js")
    assert script.headers["content-type"].startswith("text/javascript")
    landing_files.reset()


def test_without_the_stylesheet_the_page_still_carries_its_own_style(
    owner: flow.Human,
    make_client: ClientFactory,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(landing_files, "ROOT", tmp_path)
    landing_files.reset()
    html = page(owner, make_client)
    assert "<style>" in html and "landing.css" not in html and "Bring your agents" in html
    landing_files.reset()


# --- the page -----------------------------------------------------------------------------------


def test_the_header_has_the_theme_switch_hidden_and_in_the_pages_language(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    html = page(owner, make_client)
    assert '<html lang="en">' in html and "data-theme" not in html.split("<body")[0]
    assert re.search(
        r'<button type="button" class="theme-toggle" data-lp-theme hidden aria-pressed="false" '
        r'aria-label="Switch between the light and the dark theme">',
        html,
    )
    german = make_client().get("/?lang=de").text
    assert 'aria-label="Zwischen hellem und dunklem Farbschema wechseln"' in german
    assert 'aria-label="Menschen und Agents in drei Ringen' in german


def test_the_hero_is_a_dark_zone_with_the_rings_as_inline_svg(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    html = page(owner, make_client)
    assert re.search(r'<section id="s0" class="hero dz">', html)
    assert 'class="hero-rings"' in html and 'class="ring-outer"' in html
    assert 'aria-label="People and agents in three rings: you, your team, the community"' in html
    assert "<img" not in html and "<h1>Bring your agents</h1>" in html
    assert re.search(r'<header class="site-header dz">', html)


def test_the_demo_has_every_line_the_inbox_item_and_the_steps_in_the_html(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    html = page(owner, make_client, DEMO)
    assert re.search(r'<section id="s1" class="section demo" data-lp-demo>', html)
    lines = re.findall(r'<li class="(d\d) (cmd|out|note)" data-kind="\2">([^<]*)</li>', html)
    # The inbox item is the fifth step of the timeline; the lines after the fourth follow it.
    assert [(c, k) for c, k, _ in lines] == [
        ("d1", "cmd"),
        ("d2", "out"),
        ("d3", "note"),
        ("d4", "out"),
        ("d6", "out"),
        ("d7", "cmd"),
    ]
    assert [text for *_, text in lines][0] == "maity wait"
    assert re.search(
        r'<div class="inbox-item card d5" data-lp-inbox>.*Merge it\?.*CI is green\.', html
    )
    assert (
        '<span class="yes">Yes</span><span class="no">No</span><span class="reply">Reply</span>'
        in html
    )
    assert [m for m in re.findall(r'<li class="step (s\d)">', html)] == ["s1", "s2", "s3"]
    assert "The agent asks." in html and "One question, one answer." in html


def test_a_demo_without_an_inbox_item_or_subline_is_still_a_page(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    bare = {k: v for k, v in DEMO.items() if k not in ("inbox", "subline")}
    html = page(owner, make_client, bare)
    assert "data-lp-inbox" not in html and 'class="lead"' not in html and "d1 cmd" in html


def test_the_scales_are_three_columns_in_the_html(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    html = page(owner, make_client, SCALES)
    assert 'class="section section-alt scales"' in html and 'class="scales-grid"' in html
    columns = re.findall(
        r'<article class="card"><span class="tag">([^<]*)</span><h3>([^<]*)</h3>', html
    )
    assert columns == [("You", "Solo"), ("Team", "Team")]


def test_the_opensource_section_has_its_words_tiles_and_links(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    html = page(owner, make_client, OPENSOURCE)
    assert (
        "<strong>code</strong>" in html
        and "<h3>MIT</h3>" in html
        and "<h3>Self-hosted</h3>" in html
    )
    assert re.search(
        r'<a class="btn btn-secondary" href="https://example\.com/src">Source</a>', html
    )
    minimal = {
        "type": "opensource",
        "enabled": True,
        "title": "Open",
        "tiles": OPENSOURCE["tiles"][:1],
    }
    assert 'class="links"' not in page(owner, make_client, minimal)


def test_the_faq_is_details_and_the_band_carries_the_loader(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    html = page(owner, make_client, SECTIONS[3], BAND)
    assert "<details><summary>Why?</summary>" in html
    assert re.search(
        r'<section id="s2" class="band dz">.*class="band-loader".*<h2>Start</h2>', html, re.S
    )


def test_a_counter_is_its_number_for_the_script_and_a_floor_is_left_out(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    html = page(owner, make_client, SECTIONS[1])
    assert re.search(r'<b><span data-lp-count>1</span></b><span class="label">People</span>', html)
    assert "People online" not in html and "&lt; 5" not in html  # a floor is left out (§16.7)


def test_an_operators_words_are_escaped_in_every_new_section(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    evil = "<script>alert(1)</script>"
    demo = {**DEMO, "title": evil, "terminal_lines": [{"kind": "cmd", "text": evil}]}
    tiles = [{"title": evil, "text": evil}]
    html = page(owner, make_client, demo, {**OPENSOURCE, "title": evil, "tiles": tiles})
    assert "<script>alert" not in html and html.count("&lt;script&gt;alert(1)&lt;/script&gt;") >= 5


# --- what an admin may write --------------------------------------------------------------------


def put(owner: flow.Human, *sections: dict[str, Any]) -> Any:
    return owner.patch(
        ADMIN,
        {
            "enabled": True,
            "default_language": "en",
            "pages": {"en": {"title": "Maity", "description": "", "sections": [hero(), *sections]}},
            "footer": {"operator": "x", "social": []},
        },
    )


def fields(answer: Any) -> dict[str, str]:
    result: dict[str, str] = answer.json()["error"]["details"]["fields"]
    return result


def test_the_demo_and_the_opensource_section_are_valid_as_written(owner: flow.Human) -> None:
    assert put(owner, DEMO, OPENSOURCE).status_code == 200
    bare = {k: v for k, v in DEMO.items() if k not in ("inbox", "subline")}
    inbox_without_context = {**DEMO, "inbox": {"from": "a", "question": "q"}}
    minimal = {
        "type": "opensource",
        "enabled": True,
        "title": "O",
        "tiles": OPENSOURCE["tiles"][:1],
    }
    assert put(owner, bare, inbox_without_context, minimal).status_code == 200


@pytest.mark.parametrize(
    ("change", "path", "reason"),
    [
        ({"terminal_lines": []}, "terminal_lines", "invalid"),
        ({"terminal_lines": [{"kind": "cmd", "text": "x"}] * 9}, "terminal_lines", "invalid"),
        ({"terminal_lines": [{"kind": "inbox", "text": "x"}]}, "terminal_lines.0.kind", "invalid"),
        (
            {"terminal_lines": [{"kind": "cmd", "text": "x" * 201}]},
            "terminal_lines.0.text",
            "invalid",
        ),
        ({"terminal_lines": [{"kind": "cmd"}]}, "terminal_lines.0.text", "required"),
        ({"steps": DEMO["steps"][:2]}, "steps", "invalid"),
        ({"steps": [*DEMO["steps"], DEMO["steps"][0]]}, "steps", "invalid"),
        ({"inbox": {"from": "a"}}, "inbox.question", "required"),
        ({"inbox": {"from": "a", "question": "q" * 301}}, "inbox.question", "invalid"),
        ({"inbox": {"from": "a" * 81, "question": "q"}}, "inbox.from", "invalid"),
        ({"inbox": {"from": "a", "question": "q", "x": 1}}, "inbox.x", "extra_forbidden"),
        ({"subline": "s" * 301}, "subline", "invalid"),
        ({"title": None}, "title", "required"),
        ({"stray": 1}, "stray", "extra_forbidden"),
    ],
)
def test_a_bad_demo_names_its_field(
    owner: flow.Human, change: dict[str, Any], path: str, reason: str
) -> None:
    answer = put(owner, {**DEMO, **change})
    assert answer.status_code == 400
    assert fields(answer) == {f"pages.en.sections.1.{path}": reason}


@pytest.mark.parametrize(
    ("change", "path", "reason"),
    [
        ({"tiles": []}, "tiles", "invalid"),
        ({"tiles": [{"title": "t", "text": "x"}] * 4}, "tiles", "invalid"),
        ({"tiles": [{"title": "t"}]}, "tiles.0.text", "required"),
        ({"links": [{"label": "l", "href": "https://e.com"}] * 5}, "links", "invalid"),
        ({"links": [{"label": "l", "href": "javascript:alert(1)"}]}, "links.0.href", "invalid"),
        ({"markdown": "m" * 601}, "markdown", "invalid"),
        ({"markdown": "<b>x</b>"}, "markdown", "html"),
        ({"title": "t" * 121}, "title", "invalid"),
    ],
)
def test_a_bad_opensource_section_names_its_field(
    owner: flow.Human, change: dict[str, Any], path: str, reason: str
) -> None:
    answer = put(owner, {**OPENSOURCE, **change})
    assert answer.status_code == 400
    assert list(fields(answer)) == [f"pages.en.sections.1.{path}"]
    assert reason in fields(answer).values() or reason == "html"


def test_the_preview_answers_with_the_pages_policy(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    from maity_hub.routes.pages import LANDING_CSP

    draft = owner.post(
        f"{ADMIN}/preview",
        {
            "default_language": "en",
            "pages": {"en": {"title": "Draft", "description": "", "sections": [hero(), DEMO]}},
            "footer": {"operator": "x", "social": []},
        },
    )
    assert draft.status_code in (200, 201), draft.text
    shown = owner.client.get(draft.json()["url"])
    assert shown.status_code == 200
    assert shown.headers["content-security-policy"] == LANDING_CSP
    assert "data-lp-demo" in shown.text and shown.headers["x-robots-tag"] == "noindex"
