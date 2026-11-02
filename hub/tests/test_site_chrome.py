"""docs/api.md §16.7.5: the frame of the public pages, `GET /site/chrome`."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import Engine

from tests import flow
from tests.conftest import ClientFactory
from tests.test_join_host import join_client

ADMIN = "/admin/settings/landing"
LEGAL = "/admin/settings/legal"
CHROME = "/api/v1/site/chrome"
IMPRINT = {"en": {"title": "Imprint", "markdown": "Maity, Austria."}}
HERO = {
    "type": "hero",
    "enabled": True,
    "title": "Bring your agents",
    "nav_label": "Start",
    "cta_primary": {"label": "Create your account", "href": "/register?ref=hero"},
}
STEPS = {
    "type": "steps",
    "enabled": True,
    "title": "How it works",
    "nav_label": "How it works",
    "items": [{"title": "Join", "text": "Run it."}],
}
SOURCE = {
    "type": "opensource",
    "enabled": True,
    "title": "Open source",
    "tiles": [{"title": "MIT", "text": "Read it."}],
    "links": [{"label": "GitHub", "href": "https://github.com/example/maity"}],
}
SOCIAL = [
    {"label": "Mastodon", "href": "https://m.example/@maity"},
    {"label": "Fediverse", "href": "https://f.example/@maity"},
    {"label": "Query", "href": "https://q.example/p?u=/@maity"},
    {"label": "Fragment", "href": "https://q.example/p#/@maity"},
    {"label": "GitHub", "href": "https://github.com/example/maity"},
]


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    return flow.human(make_client, migrated)  # the first human: the instance admin


def publish(owner: flow.Human, **more: Any) -> None:
    hidden = {**STEPS, "enabled": False, "nav_label": "Hidden"}
    body = {
        "enabled": True,
        "default_language": "en",
        "pages": {
            "en": {"title": "Maity", "description": "", "sections": [HERO, hidden, STEPS, SOURCE]},
            "de": {"title": "Maity", "description": "", "sections": [{**HERO, "nav_label": "Los"}]},
        },
        "footer": {"operator": "Maity, Austria", "social": SOCIAL},
        **more,
    }
    done = owner.patch(ADMIN, body)
    assert done.status_code == 200, done.text


def links(model: dict[str, Any], key: str) -> list[dict[str, Any]]:
    return next(c["links"] for c in model["footer"]["columns"] if c["key"] == key)


def test_the_model_holds_the_landing_pages_frame(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    publish(owner)
    owner.patch(LEGAL, {"imprint": IMPRINT})
    answer = make_client().get(CHROME, params={"lang": "en"})
    assert answer.status_code == 200, answer.text
    model = answer.json()
    assert model["language"] == "en" and model["landing"] is True
    # Only enabled sections with a nav_label, by their index on the page.
    assert model["header"] == {
        "nav": [
            {"label": "Start", "href": "/?lang=en#s0"},
            {"label": "How it works", "href": "/?lang=en#s2"},
        ],
        "sign_in": {"label": "Sign in", "href": "/login?lang=en"},
        "cta": {"label": "Create your account", "href": "/register?ref=hero&lang=en"},
    }
    assert [c["key"] for c in model["footer"]["columns"]] == [
        "platform",
        "open_source",
        "legal",
        "follow",
    ]
    assert [link["href"] for link in links(model, "platform")] == [
        "/?lang=en#s0",
        "/?lang=en#s2",
        "/login?lang=en",
        "/register?lang=en",
    ]
    assert links(model, "legal") == [
        {"label": "Imprint", "href": "/impressum?lang=en", "rel": None}
    ]
    assert links(model, "open_source") == [
        {"label": "GitHub", "href": "https://github.com/example/maity", "rel": None}
    ]
    # GitHub is in Open source already, so Follow leaves it out.
    assert [(link["label"], link["rel"]) for link in links(model, "follow")] == [
        ("Mastodon", "me"),
        ("Fediverse", "me"),
        ("Query", None),
        ("Fragment", None),
    ]
    assert model["footer"]["operator"] == "Maity, Austria"
    assert model["footer"]["languages"] == [
        {"tag": "en", "name": "English"},
        {"tag": "de", "name": "Deutsch"},
    ]
    # Nothing beyond what the page shows.
    assert "variants" not in answer.text and "updated_by" not in answer.text


def test_rel_me_needs_the_handle_in_the_path(owner: flow.Human, make_client: ClientFactory) -> None:
    """`/@` in the query or the fragment does not make a link `rel="me"`, on the page either."""
    publish(owner)
    page = make_client().get("/").text
    assert 'href="https://f.example/@maity" rel="noopener me"' in page
    assert 'href="https://q.example/p?u=/@maity" rel="noopener"' in page
    assert 'href="https://q.example/p#/@maity" rel="noopener"' in page


def test_the_language_is_chosen_as_the_landing_pages(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    publish(owner)
    visitor = make_client()
    german = visitor.get(CHROME, headers={"Accept-Language": "de-AT,de;q=0.9"}).json()
    assert german["language"] == "de"
    assert german["header"]["nav"] == [{"label": "Los", "href": "/?lang=de#s0"}]
    assert german["header"]["sign_in"] == {"label": "Anmelden", "href": "/login?lang=de"}
    # An unknown `lang` is no error: the default language.
    assert visitor.get(CHROME, params={"lang": "xx"}).json()["language"] == "en"
    # `lang` wins over Accept-Language.
    chosen = visitor.get(CHROME, params={"lang": "en"}, headers={"Accept-Language": "de"})
    assert chosen.json()["language"] == "en"


def test_disabled_it_publishes_nothing_an_operator_prepares(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    publish(owner, enabled=False)
    visitor = make_client()
    model = visitor.get(CHROME, headers={"Accept-Language": "fr"}).json()
    assert model["language"] == "fr" and model["landing"] is False
    assert model["header"]["nav"] == [] and model["header"]["cta"] is None
    assert [c["key"] for c in model["footer"]["columns"]] == ["platform"]
    assert model["footer"]["operator"] is None and model["footer"]["languages"] == []
    assert "Mastodon" not in visitor.get(CHROME).text
    # With a legal page set, which shows them anyway, Follow and the operator are there.
    owner.patch(LEGAL, {"imprint": IMPRINT})
    model = visitor.get(CHROME, params={"lang": "en"}).json()
    assert [c["key"] for c in model["footer"]["columns"]] == ["platform", "legal", "follow"]
    assert model["footer"]["operator"] == "Maity, Austria"
    assert model["header"]["nav"] == [] and model["footer"]["languages"] == []


def test_it_is_cached_as_the_landing_page(owner: flow.Human, make_client: ClientFactory) -> None:
    publish(owner)
    visitor = make_client()
    answer = visitor.get(CHROME)
    assert answer.headers["cache-control"] == "public, max-age=60"
    assert "Accept-Language" in answer.headers["vary"]
    tag = answer.headers["etag"]
    assert visitor.get(CHROME, headers={"If-None-Match": tag}).status_code == 304
    owner.patch(ADMIN, {"footer": {"operator": "Someone else", "social": []}})
    again = visitor.get(CHROME, headers={"If-None-Match": tag})
    assert again.status_code == 200 and again.json()["footer"]["operator"] == "Someone else"


def test_the_join_host_never_serves_it(owner: flow.Human, make_client: ClientFactory) -> None:
    publish(owner)
    answer = join_client(make_client).get(CHROME, follow_redirects=False)
    assert answer.status_code in (302, 404)
    assert "Maity, Austria" not in answer.text


def test_a_legal_page_has_the_landing_pages_header_and_footer(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    """§16.7.5: the legal pages draw the frame's model, in gj6k's design (`public-pages.css`)."""
    publish(owner)
    owner.patch(LEGAL, {"imprint": IMPRINT})
    owner.patch(LEGAL, {"privacy": {**IMPRINT, "de": {"title": "Datenschutz", "markdown": "x"}}})
    page = make_client().get("/privacy", params={"lang": "en"}).text
    assert '<header class="site-header dz">' in page and 'class="theme-toggle"' not in page
    # The header links lead to the landing page's sections, not to the legal page's.
    assert 'href="/?lang=en#s0">Start</a>' in page and 'href="#s0"' not in page
    assert 'class="signin" href="/login?lang=en"' in page
    assert 'href="/register?ref=hero&amp;lang=en">Create your account</a>' in page
    # The legal pages that are set, this one marked.
    assert '<nav class="legal-toc"' in page
    assert '<a href="/impressum?lang=en">Imprint</a>' in page
    assert '<a href="/privacy?lang=en" aria-current="page">Privacy</a>' in page
    # The landing page's full footer, with the legal page's own languages.
    assert '<footer class="site-footer">' in page and 'rel="noopener me"' in page
    assert "Maity, Austria" in page
    assert '<a href="?lang=de" lang="de">Deutsch</a>' in page
    assert (
        "/assets/landing/landing.css?v=" in page and "/assets/landing/public-pages.css?v=" in page
    )
    assert "<script" not in page
    css = make_client().get("/assets/landing/public-pages.css")
    assert css.status_code == 200 and ".legal-page" in css.text


def test_a_legal_page_without_a_landing_page_keeps_its_frame_small(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    publish(owner, enabled=False)
    owner.patch(LEGAL, {"imprint": IMPRINT})
    page = make_client().get("/impressum").text
    assert '<nav class="site-nav"></nav>' in page and "btn-primary" not in page
    # A legal page is set, so Follow and the operator are there (§16.7.5).
    assert "Maity, Austria" in page and "Mastodon" in page
