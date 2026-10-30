"""docs/api.md §16.9: the store of public pages and the answer to a visitor, whatever the page
shows: the switch, the session, `?as=public`, the headers, the ETag, the rate limit."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import Engine, select

from maity_hub import clock, public_pages, render
from maity_hub import tables as t
from maity_hub.config import ConfigError, Settings
from tests import flow
from tests.conftest import ClientFactory

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
    assert got.headers["content-security-policy"] == "default-src 'none'; style-src 'unsafe-inline'"
    assert got.headers["x-content-type-options"] == "nosniff"
    assert got.headers["vary"] == "Cookie"
    assert "set-cookie" not in got.headers
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
    assert "<script" not in text


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
    make_client: ClientFactory, migrated: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    from maity_hub.ratelimit import Limiter

    monkeypatch.setattr(public_pages, "BY_ADDRESS", Limiter(2, 60))
    client = visitor(make_client)
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
