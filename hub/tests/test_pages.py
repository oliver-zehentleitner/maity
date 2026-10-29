"""docs/api.md §16.7, §16.7.1: the landing page and the legal pages as static HTML, the
counters, the drafts and the visitor's view."""

from __future__ import annotations

import re
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import Engine, update

from maity_hub import clock, landing_stats, render
from maity_hub import tables as t
from tests import flow
from tests.conftest import ClientFactory

ADMIN = "/admin/settings/landing"
LEGAL = "/admin/settings/legal"


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    landing_stats.reset()
    return flow.human(make_client, migrated)  # the first human: the instance admin


def hero(title: str = "Bring your agents") -> dict[str, Any]:
    return {
        "type": "hero",
        "enabled": True,
        "eyebrow": "Alpha",
        "title": title,
        "subline": "Share one project.",
        "cta_primary": {"label": "Create your account", "href": "/register"},
        "cta_secondary": {"label": "Docs", "href": "https://example.com/docs"},
        "note": "Some **bold** note",
    }


SECTIONS = [
    hero(),
    {"type": "stats", "enabled": True, "items": ["people", "agents", "people_online"]},
    {
        "type": "steps",
        "enabled": True,
        "title": "How it works",
        "items": [{"title": "Join", "text": "Run it.", "code": "maity join <url>"}],
    },
    {
        "type": "faq",
        "enabled": True,
        "title": "Questions",
        "items": [{"q": "Why?", "a": "Because [reasons](/login)."}],
    },
    {"type": "text", "enabled": False, "title": "Hidden", "markdown": "never shown"},
]


def publish(owner: flow.Human, sections: list[dict[str, Any]] | None = None, **more: Any) -> None:
    body = {
        "enabled": True,
        "default_language": "en",
        "pages": {
            "en": {"title": "Maity", "description": "A hub", "sections": sections or SECTIONS},
            "de": {
                "title": "Maity auf Deutsch",
                "description": "",
                "sections": [hero("Bringe deine Agenten")],
            },
        },
        "footer": {
            "operator": "Maity, Austria",
            "social": [{"label": "Mastodon", "href": "https://m.example/@maity"}],
        },
        **more,
    }
    done = owner.patch(ADMIN, body)
    assert done.status_code == 200, done.text


# --- the landing page at the root ----------


def test_a_visitor_gets_the_page_with_its_headers_and_no_script(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    publish(owner)
    answer = make_client().get("/")
    assert answer.status_code == 200 and answer.headers["content-type"].startswith("text/html")
    assert answer.headers["cache-control"] == "public, max-age=60"
    assert answer.headers["vary"] == "Cookie, Accept-Language"
    assert answer.headers["content-security-policy"] == (
        "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'; "
        "frame-ancestors 'none'"
    )
    assert "x-robots-tag" not in answer.headers and "set-cookie" not in answer.headers
    page = answer.text
    assert "<script" not in page and "<img" not in page and "onclick" not in page
    assert "<title>Maity</title>" in page and 'content="A hub"' in page
    assert '<link rel="canonical" href="https://hub.example/">' in page
    assert "<h1>Bring your agents</h1>" in page and "Share one project." in page
    assert 'href="/register">Create your account</a>' in page
    assert "<strong>bold</strong>" in page and "<code>maity join &lt;url&gt;</code>" in page
    assert "<summary>Why?</summary>" in page and 'href="/login" rel="noopener">reasons</a>' in page
    assert "never shown" not in page  # a section that is not enabled
    assert "Maity, Austria" in page and 'rel="noopener me"' in page  # a Mastodon link
    assert 'href="/login">Sign in</a>' in page


def test_the_operators_words_are_text(owner: flow.Human, make_client: ClientFactory) -> None:
    evil = hero('<script>alert("x")</script> & "q"')
    owner.patch(
        ADMIN,
        {
            "enabled": True,
            "pages": {
                "en": {
                    "title": '</title><b onload="x">',
                    "description": '"><i>',
                    "sections": [evil],
                }
            },
        },
    )
    page = make_client().get("/").text
    assert "<script" not in page and "<b onload" not in page and "<i>" not in page
    assert "&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt;" in page


def test_the_language_is_the_query_then_the_header_then_the_default(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    publish(owner)
    visitor = make_client()
    assert "<h1>Bring your agents</h1>" in visitor.get("/").text
    german = visitor.get("/?lang=de").text
    assert "<h1>Bringe deine Agenten</h1>" in german and '<html lang="de">' in german
    by_header = visitor.get("/", headers={"Accept-Language": "fr;q=0.9, de-AT;q=0.8, en;q=0.5"})
    assert "<h1>Bringe deine Agenten</h1>" in by_header.text
    unknown = visitor.get("/?lang=fr", headers={"Accept-Language": "fr"})
    assert "<h1>Bring your agents</h1>" in unknown.text  # the default language's page
    owner.patch(ADMIN, {"default_language": "de"})
    assert "<h1>Bringe deine Agenten</h1>" in visitor.get("/").text


def test_a_page_missing_a_language_falls_back_to_the_default(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    owner.patch(ADMIN, {"enabled": True, "pages": {"en": {"title": "Only", "sections": [hero()]}}})
    assert "<title>Only</title>" in make_client().get("/?lang=de").text


def test_a_session_gets_the_shell_and_as_public_shows_the_saved_page(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    publish(owner)
    signed_in = owner.client.get("/")
    assert "<title>dashboard</title>" in signed_in.text
    assert signed_in.headers["cache-control"] == "no-cache" and signed_in.headers["x-robots-tag"]
    seen = owner.client.get("/?as=public&lang=de")
    assert "<h1>Bringe deine Agenten</h1>" in seen.text
    assert '<link rel="canonical" href="https://hub.example/">' in seen.text  # the bare root
    owner.patch(ADMIN, {"enabled": False})
    assert "<title>dashboard</title>" in owner.client.get("/?as=public").text  # off: the shell
    assert "<title>dashboard</title>" in make_client().get("/").text


def test_other_cookies_and_a_dead_session_do_not_count_as_a_session(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    publish(owner)
    visitor = make_client()
    visitor.cookies.set("maity_device", "whatever")
    visitor.cookies.set("maity_session", "not-a-session")
    assert "<h1>Bring your agents</h1>" in visitor.get("/").text


def test_login_and_register_are_always_the_shell(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    publish(owner)
    for path in ("/login", "/register"):
        assert "<title>dashboard</title>" in make_client().get(path).text, path


def test_without_a_dashboard_the_root_is_the_page_or_not_found(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    publish(owner)
    assert "<h1>Bring your agents</h1>" in make_client().get("/").text


# --- the counters ----------


def test_the_counters_of_the_page_and_of_the_public_read(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    publish(owner)
    page = make_client().get("/").text
    assert re.search(r"<b>1</b><span>People</span>", page)  # the admin
    assert "People online" in page and "&lt; 5" in page  # an online count under the floor
    assert "Agents</span>" in page
    body = make_client().get("/api/v1/landing").json()
    assert set(body["stats"]) == {
        "people",
        "agents",
        "people_online",
        "online_floor",
        "computed_at",
    }
    assert body["stats"]["people_online"] is None and body["stats"]["online_floor"] == 5
    owner.patch(ADMIN, {"pages": {"en": {"title": "T", "sections": [hero()]}}})
    assert make_client().get("/api/v1/landing").json()["stats"] is None  # nothing names one


def test_the_counters_are_recomputed_every_five_minutes_only(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    start = clock.now()
    clock.set_source(lambda: start)
    publish(owner)
    first = make_client().get("/api/v1/landing").json()["stats"]["people"]
    flow.human(make_client, migrated, "second")
    assert make_client().get("/api/v1/landing").json()["stats"]["people"] == first
    later = start + timedelta(minutes=5, seconds=1)
    clock.set_source(lambda: later)
    assert make_client().get("/api/v1/landing").json()["stats"]["people"] == first + 1


def test_online_counts_show_from_the_floor_up(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    publish(owner)
    for n in range(5):
        flow.human(make_client, migrated, f"person{n}")
    with migrated.begin() as conn:
        conn.execute(update(t.human).values(last_seen_at=clock.now()))
    landing_stats.reset()
    stats = make_client().get("/api/v1/landing").json()["stats"]
    assert stats["people_online"] == 6 and stats["people"] == 6


# --- the legal pages ----------

IMPRINT = {
    "en": {"title": "Imprint", "markdown": "# Operator\n\nMaity, Austria.\n\n- one\n- two"},
    "de": {"title": "Impressum", "markdown": "Betreiber: Maity"},
}


def test_a_page_that_is_not_set_is_not_found(make_client: ClientFactory, owner: flow.Human) -> None:
    for path in ("/impressum", "/privacy", "/terms", "/impressum/2026-01-01T00:00:00Z"):
        answer = make_client().get(path)
        assert answer.status_code == 404, path
        assert answer.json()["error"]["code"] == "not_found"


def test_a_legal_page_is_static_html_with_its_version_and_its_own_policy(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    saved = owner.patch(LEGAL, {"imprint": IMPRINT}).json()
    version = saved["pages"]["imprint"]["version"]
    answer = make_client().get("/impressum")
    assert answer.status_code == 200
    assert (
        answer.headers["content-security-policy"] == "default-src 'none'; style-src 'unsafe-inline'"
    )
    assert answer.headers["cache-control"] == "public, max-age=60"
    assert answer.headers["vary"] == "Accept-Language"
    page = answer.text
    assert "<script" not in page and "<h1>Imprint</h1>" in page and f"As of {version}" in page
    assert "<h1>Operator</h1>" in page and "<li>one</li>" in page
    assert '<link rel="canonical" href="https://hub.example/impressum">' in page
    assert "Earlier versions" not in page
    german = make_client().get("/impressum?lang=de").text
    assert "<h1>Impressum</h1>" in german and f"Stand {version}" in german


def test_earlier_versions_stay_readable_also_after_the_page_is_unset(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    start = clock.now().replace(microsecond=0)
    clock.set_source(lambda: start)
    first = owner.patch(LEGAL, {"terms": {"en": {"title": "Terms 1", "markdown": "one"}}}).json()
    old = first["pages"]["terms"]["version"]
    later = start + timedelta(minutes=1)
    clock.set_source(lambda: later)
    second = owner.patch(LEGAL, {"terms": {"en": {"title": "Terms 2", "markdown": "two"}}}).json()
    new = second["pages"]["terms"]["version"]
    visitor = make_client()
    current = visitor.get("/terms").text
    assert "<h1>Terms 2</h1>" in current and f'<a href="/terms/{old}">{old}</a>' in current
    earlier = visitor.get(f"/terms/{old}").text
    assert "<h1>Terms 1</h1>" in earlier and "This is an earlier version" in earlier
    assert f'<a href="/terms/{new}">{new}</a>' in earlier
    owner.patch(LEGAL, {"terms": None})
    assert visitor.get("/terms").status_code == 404
    assert "<h1>Terms 2</h1>" in visitor.get(f"/terms/{new}").text  # unset, still readable
    assert visitor.get("/terms/2020-01-01T00:00:00Z").status_code == 404


def test_the_footer_links_the_legal_pages_that_are_set(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    publish(owner)
    assert "/impressum" not in make_client().get("/").text
    owner.patch(LEGAL, {"imprint": IMPRINT})
    owner.patch(LEGAL, {"privacy": IMPRINT})
    page = make_client().get("/").text
    assert 'href="/impressum">Imprint</a>' in page and 'href="/privacy">Privacy</a>' in page
    assert "/terms" not in page
    assert 'href="/impressum">Imprint</a>' in make_client().get("/privacy").text


def test_the_join_host_serves_neither_the_root_nor_a_legal_page(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    publish(owner)
    owner.patch(LEGAL, {"imprint": IMPRINT})
    from tests.test_join_host import join_client

    client = join_client(make_client)
    for path in ("/impressum", "/privacy", "/terms"):
        answer = client.get(path, follow_redirects=False)
        assert answer.status_code in (302, 404) and "Imprint" not in answer.text, path


# --- the Markdown ----------


@pytest.mark.parametrize(
    ("source", "html"),
    [
        ("# Head", "<h1>Head</h1>"),
        ("###### Six", "<h6>Six</h6>"),
        ("a *b* **c** `d`", "<p>a <em>b</em> <strong>c</strong> <code>d</code></p>"),
        ("- a\n- b", "<ul><li>a</li><li>b</li></ul>"),
        ("1. a\n2. b", "<ol><li>a</li><li>b</li></ol>"),
        ("> quote", "<blockquote><p>quote</p></blockquote>"),
        ("```\n<b>&\n```", "<pre><code>&lt;b&gt;&amp;</code></pre>"),
        ("one\ntwo", "<p>one<br>two</p>"),
        ("[x](/login)", '<p><a href="/login" rel="noopener">x</a></p>'),
        (
            "see https://e.com/a.",
            '<p>see <a href="https://e.com/a" rel="noopener">https://e.com/a</a>.</p>',
        ),
        ("a < b & c", "<p>a &lt; b &amp; c</p>"),
        ("```\nnever closed\n<b>", "<pre><code>never closed\n&lt;b&gt;</code></pre>"),
    ],
)
def test_the_markdown_renderer(source: str, html: str) -> None:
    assert render.markdown(source) == html


def test_a_link_that_the_validator_would_refuse_is_text() -> None:
    assert "<a " not in render.markdown("[x](javascript:alert(1))")
    assert "<a " not in render.markdown("[x](//evil.example)")


@pytest.mark.parametrize(
    ("offered", "default", "query", "header", "expected"),
    [
        (["en", "de"], "en", "de", None, "de"),
        (["en", "de"], "en", "fr", "de", "de"),
        (["en", "de"], "en", None, "de-AT,de;q=0.9,en;q=0.5", "de"),
        (["en", "de"], "en", None, "en;q=0.2, de;q=0.9", "de"),
        (["en", "de"], "de", None, "fr", "de"),
        (["en"], "de", None, None, "en"),
        (["en", "de"], "en", None, "de;q=0", "en"),
        (["en", "de"], "en", None, "junk;q=x, de", "de"),
    ],
)
def test_the_language_negotiation(
    offered: list[str], default: str, query: str | None, header: str | None, expected: str
) -> None:
    assert render.choose_language(offered, default, query, header) == expected
