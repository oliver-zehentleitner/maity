"""docs/api.md §16.9: the store of public pages and the answer to a visitor, whatever the page
shows: the switch, the session, `?as=public`, the headers, the ETag, the rate limit."""

from __future__ import annotations

import re
from html import escape
from typing import Any

import pytest
from sqlalchemy import Engine, select

from maity_hub import clock, landing_files, middleware, public_pages, render
from maity_hub import shell as shell_module
from maity_hub import tables as t
from maity_hub.config import ConfigError, Settings
from tests import flow
from tests.conftest import ClientFactory
from tests.test_pages import hero, publish

PATH = "/oz-team"


def store(engine: Engine, path: str = PATH, body: str | None = None) -> None:
    page = body or render.page_document(
        lang="en",
        title="OZ Team",
        canonical=f"https://hub.example{path}",
        content="<h1>OZ Team</h1><p>We build things.</p>",
    )
    with engine.begin() as conn:
        public_pages.put(
            conn,
            path=path,
            kind="organisation",
            target_id="org-1",
            body=page,
            inputs="x",
            lastmod=clock.now(),
            view="organisation_page",
            data={},
        )


@pytest.fixture(autouse=True)
def _fresh() -> None:
    public_pages.BY_ADDRESS.reset() if hasattr(public_pages.BY_ADDRESS, "reset") else None


def visitor(make_client: ClientFactory, **overrides: Any) -> Any:
    """A client of a hub that serves pages. Made before a test stores its pages: the app
    renders every page again when it starts (§16.9), which deletes what was stored before."""
    return make_client(public_pages=True, **overrides)


def test_a_visitor_gets_the_stored_page_with_the_headers_of_the_contract(
    make_client: ClientFactory, migrated: Engine
) -> None:
    client = visitor(make_client)
    store(migrated)
    got = client.get(PATH)
    assert got.status_code == 200
    assert "<h1>OZ Team</h1>" in got.text
    assert got.headers["content-type"].startswith("text/html")
    assert got.headers["cache-control"] == "public, max-age=60"
    # In its frame (§16.7.5): the landing page's stylesheets, fonts and its one script.
    assert got.headers["content-security-policy"] == (
        "default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; font-src 'self'; "
        "img-src 'self'; base-uri 'none'; frame-ancestors 'none'"
    )
    assert got.headers["x-content-type-options"] == "nosniff"
    assert got.headers["vary"] == "Cookie, Accept-Language"
    assert "set-cookie" not in got.headers
    assert got.headers["etag"] == public_pages.etag_of(got.text)


def test_the_frame_is_put_around_the_stored_page_when_it_is_served(
    make_client: ClientFactory, migrated: Engine
) -> None:
    """§16.9, §16.7.5: the landing page's header and footer around the content as stored; the
    row itself is not rendered again or changed."""
    client = visitor(make_client)
    store(migrated)
    with migrated.connect() as conn:
        [row] = conn.execute(select(t.public_page)).all()
    page = client.get(PATH).text
    content = row.body.split('<main class="wrap">', 1)[1].rsplit("</main>", 1)[0]
    assert f'<div class="stored-page"><div class="wrap">{content}</div></div>' in page
    assert page.index('<header class="site-header dz">') < page.index(content)
    assert page.index(content) < page.index('<footer class="site-footer">')
    assert '<html lang="en">' in page and "<title>OZ Team</title>" in page
    assert '<link rel="canonical" href="https://hub.example/oz-team">' in page
    assert "/assets/landing/public-pages.css?v=" in page
    # The page has one language, the content's: no hreflang links.
    assert "hreflang" not in page
    with migrated.connect() as conn:
        assert conn.execute(select(t.public_page.c.body)).scalar_one() == row.body


def only_the_frames_script(html: str) -> bool:
    """The page loads the landing page's script and no other (req-q34v0gr2rbw2)."""
    return re.findall(r"<script[^>]*>", html) == [
        f'<script src="{landing_files.url("landing.js")}" defer>'
    ]


def controls(html: str) -> tuple[str, str, list[str]]:
    """The header's theme switch, the footer's language row and the scripts a page loads."""
    switch = re.search(r'<button type="button" class="theme-toggle" data-lp-theme[^>]*>', html)
    langs = re.search(r'<p class="langs">.*?</p>', html, re.S)
    assert switch is not None and langs is not None
    return switch.group(0), langs.group(0), re.findall(r'<script src="([^"]*)"', html)


def test_the_frame_has_the_landing_pages_theme_switch_and_language_row(
    make_client: ClientFactory, migrated: Engine
) -> None:
    """req-q34v0gr2rbw2: a stored page in its frame has the same header and footer controls as the
    landing page; its language links keep `as=public` and change the frame's language only."""
    owner = flow.human(make_client, migrated)
    publish(owner, [hero()])
    client = visitor(make_client)
    store(migrated)
    landing = client.get("/").text
    framed = client.get(PATH, params={"as": "public"}).text
    switch, langs, scripts = controls(landing)
    framed_switch, framed_langs, framed_scripts = controls(framed)
    assert framed_switch == switch
    assert framed_scripts == scripts == [landing_files.url("landing.js")]
    tags = re.findall(r'<a href="\?lang=([a-z-]+)" lang="\1">', langs)
    assert len(tags) > 1
    assert re.findall(r'<a href="\?as=public&amp;lang=([a-z-]+)" lang="\1">', framed_langs) == tags
    assert framed_langs.replace("?as=public&amp;lang=", "?lang=") == langs
    german = client.get(PATH, params={"as": "public", "lang": tags[1]}).text
    assert (
        '<html lang="en">' in german and f'<footer lang="{tags[1]}" class="site-footer">' in german
    )


def test_the_stored_content_stays_data_inside_the_frame(
    make_client: ClientFactory, migrated: Engine
) -> None:
    """What a member wrote was escaped when the page was rendered; the frame never unescapes it."""
    client = visitor(make_client)
    words = '<script>alert(1)</script> & "quoted"'
    store(
        migrated,
        body=render.page_document(
            lang="en",
            title=words,
            canonical="https://hub.example/oz-team",
            content=f"<h1>{escape(words)}</h1>",
        ),
    )
    page = client.get(PATH).text
    # The frame's one script is the landing page's own file; nothing of the content runs.
    assert only_the_frames_script(page)
    assert "<h1>&lt;script&gt;alert(1)&lt;/script&gt; &amp; &quot;quoted&quot;</h1>" in page
    assert "<title>&lt;script&gt;alert(1)&lt;/script&gt; &amp; &quot;quoted&quot;</title>" in page


def test_the_page_keeps_its_language_and_the_frame_follows_the_reader(
    make_client: ClientFactory, migrated: Engine
) -> None:
    client = visitor(make_client)
    store(migrated)
    english = client.get(PATH)
    german = client.get(PATH, params={"lang": "de"})
    assert '<html lang="en">' in german.text
    assert '<header lang="de" class="site-header dz">' in german.text
    assert '<footer lang="de" class="site-footer">' in german.text
    assert 'lang="de"' not in english.text
    # The frame is part of the answer, and so of its tag (§16.9).
    assert german.headers["etag"] == public_pages.etag_of(german.text)
    assert german.headers["etag"] != english.headers["etag"]
    stale = client.get(
        PATH, params={"lang": "de"}, headers={"If-None-Match": english.headers["etag"]}
    )
    assert stale.status_code == 200
    same = client.get(
        PATH, params={"lang": "de"}, headers={"If-None-Match": german.headers["etag"]}
    )
    assert same.status_code == 304


def test_a_stored_page_of_another_shape_is_served_bare(
    make_client: ClientFactory, migrated: Engine
) -> None:
    client = visitor(make_client)
    store(migrated, body="<!doctype html><title>old</title><p>kept</p>")
    got = client.get(PATH)
    assert got.text == "<!doctype html><title>old</title><p>kept</p>"
    assert got.headers["content-security-policy"] == public_pages.CSP
    assert got.headers["vary"] == "Cookie"
    assert got.headers["etag"] == public_pages.etag_of(got.text)


def test_the_page_carries_its_title_description_and_canonical_link(
    make_client: ClientFactory, migrated: Engine
) -> None:
    client = visitor(make_client)
    store(migrated)
    text = client.get(PATH).text
    assert "<title>OZ Team</title>" in text
    assert '<meta name="description" content="OZ Team We build things.">' in text
    assert '<link rel="canonical" href="https://hub.example/oz-team">' in text
    assert only_the_frames_script(text)


def test_the_description_is_cut_first_and_then_escaped(migrated: Engine) -> None:
    long = "x" * 150 + " &lt;b&gt; &amp; more words after the cut"
    document = render.page_document(
        lang="en", title="T", canonical="https://hub.example/t", content=f"<p>{long}</p>"
    )
    assert render.text_of("<p>a &amp; b</p>") == "a & b"
    meta = document.split('<meta name="description" content="')[1].split('">')[0]
    assert meta == "x" * 150 + " &lt;b&gt; &amp; mor"  # 160 characters of text, then escaped


def test_without_the_switch_the_address_is_the_shell(
    make_client: ClientFactory, migrated: Engine
) -> None:
    store(migrated)
    got = make_client().get(PATH)  # MAITY_PUBLIC_PAGES defaults to off
    assert got.status_code == 200
    assert "dashboard" in got.text and "OZ Team" not in got.text
    assert got.headers["vary"] == "Cookie"
    assert got.headers["x-robots-tag"] == "noindex"


def test_an_address_without_a_page_is_the_shell(
    make_client: ClientFactory, migrated: Engine
) -> None:
    client = visitor(make_client)
    store(migrated)
    got = client.get("/nothing-here")
    assert got.status_code == 200 and "dashboard" in got.text


def test_a_session_gets_the_shell_and_as_public_the_page(
    make_client: ClientFactory, migrated: Engine
) -> None:
    member = flow.human(lambda **kw: make_client(public_pages=True, **kw), migrated)
    store(migrated)
    asked = member.client.get(PATH)  # the session cookie is the client's
    assert "dashboard" in asked.text and "OZ Team" not in asked.text
    shown = member.client.get(PATH, params={"as": "public"})
    assert "<h1>OZ Team</h1>" in shown.text
    assert "set-cookie" not in shown.headers


def test_a_conditional_request_is_not_modified_and_head_has_no_body(
    make_client: ClientFactory, migrated: Engine
) -> None:
    client = visitor(make_client)
    store(migrated)
    etag = client.get(PATH).headers["etag"]
    same = client.get(PATH, headers={"If-None-Match": etag})
    assert same.status_code == 304 and same.content == b""
    assert same.headers["etag"] == etag
    assert client.get(PATH, headers={"If-None-Match": '"other"'}).status_code == 200
    head = client.head(PATH)
    assert head.status_code == 200 and head.content == b""
    assert head.headers["etag"] == etag


def test_a_page_taken_off_is_the_shell_at_once(
    make_client: ClientFactory, migrated: Engine
) -> None:
    client = visitor(make_client)
    store(migrated)
    assert "OZ Team" in client.get(PATH).text
    with migrated.begin() as conn:
        assert public_pages.remove(conn, "organisation", "org-1") == 1
    assert "OZ Team" not in client.get(PATH).text
    store(migrated)
    with migrated.begin() as conn:
        assert public_pages.clear(conn) == 1
        assert conn.execute(select(t.public_page)).all() == []


def test_a_page_stored_again_replaces_the_one_before(
    make_client: ClientFactory, migrated: Engine
) -> None:
    store(migrated, body="<!doctype html><title>one</title>")
    store(migrated, body="<!doctype html><title>two</title>")
    with migrated.connect() as conn:
        [row] = conn.execute(select(t.public_page)).all()
    assert "two" in row.body and row.etag == public_pages.etag_of(row.body)


def test_the_page_is_rate_limited_by_source_address(
    make_client: ClientFactory, migrated: Engine
) -> None:
    client = visitor(make_client, public_page_limit=(2, 60))  # MAITY_PUBLIC_PAGE_LIMIT
    store(migrated)
    assert [client.get(PATH).status_code for _ in range(3)] == [200, 200, 429]
    # the shell is not counted
    assert client.get("/nothing-here").status_code == 200


def test_only_get_and_head_reach_a_page(make_client: ClientFactory, migrated: Engine) -> None:
    client = visitor(make_client)
    store(migrated)
    assert client.post(PATH, json={}).status_code == 404


def test_the_links_of_a_page_are_nofollow_ugc() -> None:
    html = render.markdown(
        "see [the docs](https://example.com/docs) and https://example.org/x", ugc=True
    )
    assert html.count('rel="nofollow ugc"') == 2
    assert 'rel="noopener"' not in html
    assert 'rel="noopener"' in render.markdown("[a](https://example.com/a)")


def test_the_switches_are_read_from_the_environment() -> None:
    base = {"MAITY_DATABASE_URL": "sqlite://"}
    defaults = Settings.from_env(base)
    assert (defaults.public_pages, defaults.public_pages_render) == (False, "on_change")
    assert defaults.public_pages_interval_hours == 6
    assert defaults.public_pages_snapshot_minutes == 5
    assert (
        Settings.from_env(
            {**base, "MAITY_PUBLIC_PAGES_SNAPSHOT_MINUTES": "60"}
        ).public_pages_snapshot_minutes
        == 60
    )
    on = Settings.from_env(
        {
            **base,
            "MAITY_PUBLIC_PAGES": "on",
            "MAITY_PUBLIC_PAGES_RENDER": "interval",
            "MAITY_PUBLIC_PAGES_INTERVAL_HOURS": "24",
        }
    )
    assert (on.public_pages, on.public_pages_render, on.public_pages_interval_hours) == (
        True,
        "interval",
        24,
    )
    for name, value in (
        ("MAITY_PUBLIC_PAGES", "yes"),
        ("MAITY_PUBLIC_PAGES_RENDER", "daily"),
        ("MAITY_PUBLIC_PAGES_INTERVAL_HOURS", "0"),
        ("MAITY_PUBLIC_PAGES_INTERVAL_HOURS", "25"),
        ("MAITY_PUBLIC_PAGES_INTERVAL_HOURS", "1.5"),
        ("MAITY_PUBLIC_PAGES_SNAPSHOT_MINUTES", "0"),
        ("MAITY_PUBLIC_PAGES_SNAPSHOT_MINUTES", "61"),
    ):
        with pytest.raises(ConfigError):
            Settings.from_env({**base, name: value})


def test_the_join_host_never_answers_a_page(make_client: ClientFactory, migrated: Engine) -> None:
    """Nothing but the join is served there (§1.1): a page's address is sent to the public
    root, never answered from the stored page."""
    client = make_client(
        base_url="https://join.example", public_pages=True, join_url="https://join.example"
    )
    store(migrated)
    got = client.get(PATH, follow_redirects=False)
    assert got.status_code == 302 and got.headers["location"] == "https://hub.example/"
    assert "OZ Team" not in got.text


def test_a_slash_at_the_end_leads_a_visitor_to_the_page(
    make_client: ClientFactory, migrated: Engine
) -> None:
    client = visitor(make_client)
    store(migrated)
    got = client.get(f"{PATH}/?as=public", follow_redirects=False)
    assert (got.status_code, got.headers["location"]) == (308, f"{PATH}?as=public")
    assert client.get(f"{PATH}/", follow_redirects=True).status_code == 200
    assert client.get("/nobody/here/", follow_redirects=False).status_code != 308


def test_a_page_comes_inside_the_shell_for_a_crawler_and_the_dashboard() -> None:
    shell = (
        b'<html><head><title>Maity</title><meta name="description" content="x"></head><body>'
        b'<script src="js/app.js"></script><main id="main"><p>Loading</p></main></body></html>'
    )
    page = render.page_document(
        lang="en", title="A & B", canonical="https://hub.example/a", content="<h1>Text</h1>"
    )
    made = shell_module.page_in_shell(shell, page)
    assert made is not None
    assert b"<title>A &amp; B</title>" in made and b"Loading" not in made
    assert b'<link rel="canonical" href="https://hub.example/a">' in made
    assert b'<main id="main" data-public-page><h1>Text</h1></main>' in made
    assert b'src="js/app.js"' in made and b'content="x"' not in made
    social = shell_module.page_in_shell(
        b'<html><title>M</title><meta property="og:title" content="Maity">'
        b'<meta property="og:description" content="Old"><main id="main"></main></html>',
        page,
    )
    assert social is not None
    assert b'property="og:title" content="A &amp; B"' in social and b'"Maity"' not in social
    assert b'content="Old"' not in social
    quoted = render.page_document(
        lang="en",
        title='x" onmouseover="y',
        canonical="https://hub.example/a",
        content='<h1>a" b</h1>',
    )
    escaped = shell_module.page_in_shell(
        b'<html><title>M</title><meta property="og:title" content="Maity">'
        b'<meta property="og:description" content="Old"><main id="main"></main></html>',
        quoted,
    )
    assert escaped is not None
    assert b'property="og:title" content="x&quot; onmouseover=&quot;y"' in escaped
    assert b'property="og:description" content="a&quot; b"' in escaped
    assert shell_module.page_in_shell(b"<html></html>", page) is None
    assert shell_module.page_in_shell(shell, "<html></html>") is None


def test_a_visitor_gets_the_shell_with_the_page_and_as_public_the_bare_page(
    make_client: ClientFactory, migrated: Engine, web_dir: Any
) -> None:
    (web_dir / "index.html").write_text(
        '<html><head><title>Maity</title></head><body><script src="js/app.js"></script>'
        '<main id="main"><p>Loading</p></main></body></html>'
    )
    client = visitor(make_client)
    store(migrated)
    got = client.get("/oz-team")
    assert got.status_code == 200 and "<h1>OZ Team</h1>" in got.text and "js/app.js" in got.text
    assert (
        "x-robots-tag" not in got.headers and got.headers["cache-control"] == "public, max-age=60"
    )
    assert client.get("/oz-team", headers={"If-None-Match": got.headers["etag"]}).status_code == 304
    assert got.headers["content-security-policy"] == middleware.CSP
    assert got.headers["x-frame-options"] == "DENY"
    bare = client.get("/oz-team?as=public")
    assert (
        "js/app.js" not in bare.text
        and "default-src 'none'" in bare.headers["content-security-policy"]
    )
