"""docs/api.md §16.13: the product line at the end of the hub's own pages, and no referrer on a
page with a token in its path."""

from __future__ import annotations

import base64
import hashlib
import re
from datetime import UTC, datetime
from html import unescape
from typing import Any

import pytest
from sqlalchemy import Engine, update

from maity_hub import (
    catalog,
    clock,
    landing,
    landing_files,
    legal,
    maintenance,
    product_line,
    render,
)
from maity_hub import tables as t
from maity_hub.routes import register_page
from tests import factory, flow
from tests.conftest import ClientFactory
from tests.test_email_sign_in import ask, mail, setup
from tests.test_join_host import create, join_client, token_of
from tests.test_mail_links import link, mail_hub, stored

LINKS = [
    "https://github.com/oliver-zehentleitner",
    "https://maity.team/oliver-zehentleitner",
    "https://github.com/oliver-zehentleitner/maity/issues",
    "https://github.com/oliver-zehentleitner/maity/blob/main/SECURITY.md",
]


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Any) -> flow.Human:
    human = flow.human(make_client, migrated)
    flow.project(human)
    return human


def text_of(html: str) -> str:
    return " ".join(unescape(re.sub(r"<[^>]*>", " ", html)).split())


def test_the_line_has_its_parts_its_links_and_no_style() -> None:
    clock.set_source(lambda: datetime(2031, 5, 1, tzinfo=UTC))
    line = product_line.html("en")
    assert text_of(line) == (
        "Maity 2031 · Made with ♥ by Oliver Zehentleitner on & · "
        "Found a bug? · Found a vulnerability?"
    )  # the year from the hub's clock, never a fixed one
    assert re.findall(r'<a href="([^"]+)"', line) == LINKS  # absolute, the Maity page without @
    assert line.count('target="_blank" rel="noopener noreferrer"') == 4
    assert 'aria-label="GitHub"' in line and 'aria-label="Maity"' in line
    assert '<span role="img" aria-label="love">♥</span>' in line
    # Three icons and the three separators, which are drawn, not read.
    assert line.count("<svg") == 3 and line.count('aria-hidden="true"') == 6
    assert line.count('<span aria-hidden="true"> · </span>') == 3
    # Presentation attributes only: the pages' policies allow no inline style (§16.13).
    for forbidden in ("style=", "<style", "<use", "<title", "<img"):
        assert forbidden not in line


def test_the_line_is_in_the_pages_language() -> None:
    line = product_line.html("de")
    assert "Einen Fehler gefunden?" in line and "Mit " in line and " auf " in line
    assert 'aria-label="Liebe"' in line
    assert 'aria-label="GitHub"' in line  # names are never translated


def test_every_language_names_each_placeholder_exactly_once() -> None:
    for language in ["en", "de", "es", "fr", "it", "ja", "ko", "nl", "pt", "zh-Hans"]:
        assert product_line.well_formed(catalog.section("product", language)["made_by"]), language


@pytest.mark.parametrize(
    "sentence",
    [
        "Mit {heart} von {name} auf {github}",  # one missing
        "Mit {heart} von {name} auf {github} & {github} {maity}",  # one twice
        "Mit {heart} von {name} auf {github} & {maity} {extra}",  # another one
    ],
)
def test_a_sentence_that_is_not_well_formed_falls_back_to_english(
    monkeypatch: pytest.MonkeyPatch, sentence: str
) -> None:
    real = catalog.section

    def section(name: str, language: object) -> dict[str, str]:
        found = real(name, language)
        if name == "product" and language == "de":
            return {**found, "made_by": sentence}
        return found

    monkeypatch.setattr(catalog, "section", section)
    line = product_line.html("de")
    assert "Made with" in line and " on " in line
    assert "Einen Fehler gefunden?" in line  # the rest stays German
    assert line.count('href="https://github.com/oliver-zehentleitner"') == 1


def test_the_sentence_is_text_never_markup(monkeypatch: pytest.MonkeyPatch) -> None:
    real = catalog.section

    def section(name: str, language: object) -> dict[str, str]:
        found = real(name, language)
        if name == "product" and language == "de":
            return {**found, "made_by": "<b>{heart}</b> {name} {github} {maity}"}
        return found

    monkeypatch.setattr(catalog, "section", section)
    line = product_line.html("de")
    assert "&lt;b&gt;" in line and "<b>" not in line


def test_the_strict_pages_allow_exactly_the_style_block_by_its_hash() -> None:
    # The header's hash is the block's: an edit to STYLE cannot silently break the pages.
    block = re.fullmatch(r"<style>(.*)</style>", product_line.HEAD, re.S)
    assert block is not None and block[1] == product_line.STYLE
    digest = base64.b64encode(hashlib.sha256(block[1].encode()).digest()).decode()
    assert f"default-src 'self'; style-src 'sha256-{digest}'" == product_line.CSP
    assert "unsafe-inline" not in product_line.CSP
    assert ".product-line{text-align:center;color:var(--muted," in product_line.STYLE
    # Those pages have no dark theme: the mark keeps its light fill there.
    assert "prefers-color-scheme" not in product_line.STYLE


def strict(response: Any) -> str:
    """The page, after checking it carries the block its policy allows, and no referrer."""
    page = bytes(response.body).decode() if hasattr(response, "body") else response.text
    assert response.headers["Content-Security-Policy"] == product_line.CSP
    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert page.count("<style") == 1 and product_line.HEAD in page
    assert 'class="product-line"' in page
    return page


def test_the_maintenance_page_ends_with_the_line_and_sends_no_referrer() -> None:
    found: dict[str, Any] = {"until": "2026-11-03T12:00:00Z", "text": "Upgrade"}
    response = maintenance.refusal_page(found)
    page = strict(response)
    assert page.index("</main>") < page.index('class="product-line"') < page.index("</body>")
    assert response.headers["Retry-After"]


def test_the_registration_link_page_ends_with_the_line() -> None:
    page = bytes(register_page._dead().body).decode()
    assert 'class="product-line"' in page
    # Its policy allows its stylesheet: the line centred and muted, the mark follows a dark
    # theme there (§16.13).
    assert product_line.STYLE + product_line.DARK in page
    german = render.form_document(lang="de", title="t", content="", footer="")
    assert "Einen Fehler gefunden?" in german  # in the page's language


def test_a_mail_link_page_stands_in_the_frame_in_the_humans_language(
    make_client: ClientFactory, migrated: Engine
) -> None:
    # §16.7.5, §18.6: the frame and its footer instead of the product line; words as before.
    client = make_client(mail=mail_hub().mail)
    dead = client.get("/mail/unsubscribe/garbage")
    assert dead.status_code == 404
    assert "<h1>This link no longer works.</h1>" in framed(dead) and "<form" not in dead.text
    human_id = factory.human(migrated, "maintainer")
    stored(migrated, human_id, {"email": {"language": "de"}})
    page = framed(client.get(f"/mail/unsubscribe/{link(human_id)}"))
    assert '<html lang="de">' in page and "Einen Fehler gefunden?" not in page
    # The one explicit button, in the door's look; the GET changed nothing (§18.6).
    assert page.count("<form") == 1 and page.count("<button") == 1
    assert '<form method="post"><button type="submit" class="btn btn-primary">' in page
    stored_dead = client.get(f"/mail/unsubscribe/{link(human_id, epoch=7)}")
    assert stored_dead.status_code == 404 and '<html lang="de">' in framed(stored_dead)
    done = client.post(f"/mail/unsubscribe/{link(human_id)}")
    assert done.status_code == 200 and "<form" not in framed(done)


# The mail link pages' one policy, written out: a change to it is a change to this line
# (tsk-w62n5p0v9d47). Only the hub's own sheets, fonts and images, the fallback by its hash.
PINNED = (
    "default-src 'none'; style-src 'self' 'sha256-{fallback}'; font-src 'self'; "
    "img-src 'self'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'"
)


@pytest.mark.parametrize(
    "method,path",
    [
        ("get", "/mail/verify/garbage"),
        ("post", "/mail/verify/garbage"),
        ("get", "/mail/unsubscribe/garbage"),
        ("post", "/mail/unsubscribe/garbage"),
        ("get", "/mail/second-factor-reset/garbage"),
        ("post", "/mail/second-factor-reset/garbage"),
        ("get", "/mail/account-deletion/garbage"),
        ("post", "/mail/account-deletion/garbage"),
        ("get", "/mail/sign-in/garbage"),
    ],
)
def test_every_mail_link_page_answers_the_pinned_policy_and_its_sheets_load_under_it(
    make_client: ClientFactory, method: str, path: str
) -> None:
    fallback = base64.b64encode(hashlib.sha256(render.STYLE.encode()).digest()).decode()
    assert PINNED.format(fallback=fallback) == render.DOOR_CSP
    client = make_client(mail=mail_hub().mail)
    response = getattr(client, method)(path)
    assert response.status_code == 404
    assert response.headers["Content-Security-Policy"] == PINNED.format(fallback=fallback)
    page = framed(response)
    # Each stylesheet is the hub's own, same origin ('self'), and is served as a stylesheet.
    sheets = re.findall(r'<link rel="stylesheet" href="([^"]+)">', page)
    assert [s.split("?")[0] for s in sheets] == [
        "/assets/landing/landing.css",
        "/assets/landing/public-pages.css",
    ]
    for sheet in sheets:
        served = client.get(unescape(sheet))
        assert served.status_code == 200, sheet
        assert served.headers["content-type"].startswith("text/css")
        assert served.headers["x-content-type-options"] == "nosniff"
        # What the sheet loads is the hub's own as well: font-src and img-src 'self', which a
        # `data:` url does not match either.
        for url in re.findall(r"url\(([^)]+)\)", served.text):
            url = url.strip("'\"")
            assert not re.match(r"[a-z]+:|//", url), url


def test_a_page_whose_words_the_language_lacks_has_an_english_line(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real = catalog.speaks
    monkeypatch.setattr(
        catalog, "speaks", lambda name, lang: False if name == "mail_links" else real(name, lang)
    )
    assert "Found a bug?" in product_line.html("de", "mail_links")
    assert "Einen Fehler gefunden?" in product_line.html("de", "sign_in")


def framed(response: Any) -> str:
    """A sign-in link page in the frame (§16.7.5): the landing page's header, door and footer
    under the landing page's stylesheets, no script, no inline style, no product line, and its
    policy and no referrer (the token is in the address)."""
    page = str(response.text)
    assert response.headers["Content-Security-Policy"] == render.DOOR_CSP
    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert page.count('<header class="site-header') + page.count("<header lang=") == 1
    assert page.count('class="site-footer"') == 1 and 'class="door-page"' in page
    # The panel without a pitch, as the dashboard's door() draws it: empty, so public-pages.css
    # shows the art large and hides the panel at phone width.
    assert '<aside class="door-panel" aria-hidden="true"></aside>' in page
    for sheet in ("landing.css", "public-pages.css"):
        assert f'href="/assets/landing/{sheet}?v=' in page
    assert "<script" not in page and "<style" not in page
    # Not even the header mark's style attributes: the policy would block them (§16.7.5).
    assert "style=" not in page and 'class="mark"' in page
    # The frame's footer stands in the line's place, as on the framed /login (req-5k1gvfsmcg9k).
    assert "product-line" not in page and "Found a bug?" not in page
    return page


def test_the_sign_in_link_page_stands_in_the_frame_in_the_humans_language(
    make_client: ClientFactory, migrated: Engine
) -> None:
    client, human = setup(make_client, migrated)
    with migrated.begin() as conn:
        conn.execute(
            update(t.human)
            .where(t.human.c.id == human)
            .values(interface_language="de", display_name='<b>Ada & "Co"</b>')
        )
    ask(client)
    url, _ = mail(migrated)
    page = framed(client.get(url, headers={"accept-language": "fr"}))
    assert '<html lang="de">' in page
    title = "Bei Maity anmelden als &lt;b&gt;Ada &amp; &quot;Co&quot;&lt;/b&gt; (ada)"
    assert f"<title>{title}</title>" in page and f"<h1>{title}</h1>" in page
    assert "<b>Ada" not in page
    # One explicit button, the GET's form field next to its cookie (§2.6.3).
    assert page.count("<button") == 1 and page.count("<form") == 1
    assert '<form method="post">' in page
    assert ">Auf diesem Gerät anmelden</button>" in page
    form = re.search(r'name="form" value="([^"]+)"', page)
    assert form is not None and form[1] == client.cookies.get("maity_form")


def test_the_dead_sign_in_link_stands_in_the_frame_in_the_browsers_language(
    make_client: ClientFactory, migrated: Engine
) -> None:
    client, _ = setup(make_client, migrated)
    dead = client.get("/mail/sign-in/garbage", headers={"accept-language": "de, en;q=0.5"})
    assert dead.status_code == 404
    page = framed(dead)
    assert '<html lang="de">' in page and "<h1>Dieser Link funktioniert nicht mehr.</h1>" in page
    assert "<form" not in page and "<button" not in page
    english = framed(client.get("/mail/sign-in/garbage"))
    assert "<h1>This link no longer works.</h1>" in english
    # A used link is the same page (never which reason).
    ask(client)
    url, _ = mail(migrated)
    form = re.search(r'name="form" value="([^"]+)"', client.get(url).text)
    assert form is not None
    done = client.post(
        url,
        data={"form": form[1]},
        headers={"sec-fetch-site": "same-origin"},
        follow_redirects=False,
    )
    assert done.status_code == 303
    again = client.get(url)
    assert again.status_code == 404 and "<h1>This link no longer works.</h1>" in framed(again)


def test_a_door_page_without_the_stylesheets_carries_the_style_its_policy_allows(
    monkeypatch: pytest.MonkeyPatch, migrated: Engine
) -> None:
    digest = base64.b64encode(hashlib.sha256(render.STYLE.encode()).digest()).decode()
    assert f"style-src 'self' 'sha256-{digest}';" in render.DOOR_CSP
    assert "unsafe-inline" not in render.DOOR_CSP and "script-src" not in render.DOOR_CSP
    assert "form-action 'self'" in render.DOOR_CSP
    monkeypatch.setattr(landing_files, "url", lambda name: None)
    with migrated.connect() as conn:
        setting, served = landing.stored(conn), legal.public(legal.stored(conn))
    page = render.door_document(
        lang="en",
        title="t",
        content="<h1>t</h1>",
        setting=setting,
        legal=served,
        stats=None,
        accept_language=None,
    )
    assert f"<style>{render.STYLE}</style>" in page and "<link" not in page


def test_the_join_page_in_a_browser_ends_with_the_line_and_sends_no_referrer(
    make_client: ClientFactory, owner: flow.Human
) -> None:
    token = token_of(create(owner))
    html = join_client(make_client).get(f"/{token}", headers={"Accept": "text/html"})
    strict(html)
    public = make_client().get(f"/join/{token}", headers={"Accept": "text/html"})
    strict(public)
    # The agent's Markdown answer carries no line (§16.13).
    markdown = make_client().get(f"/join/{token}")
    assert "product-line" not in markdown.text and "Found a bug?" not in markdown.text
