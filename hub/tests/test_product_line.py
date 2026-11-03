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

from maity_hub import catalog, clock, maintenance, product_line, render
from maity_hub import tables as t
from maity_hub.routes import email_sign_in, register_page
from tests import factory, flow
from tests.conftest import ClientFactory
from tests.test_email_sign_in import ask, mail, setup
from tests.test_join_host import create, join_client, token_of
from tests.test_mail_links import link, mail_hub, stored

LINKS = [
    "https://github.com/oliver-zehentleitner/maity/issues",
    "https://github.com/oliver-zehentleitner",
    "https://maity.team/oliver-zehentleitner",
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
        "Maity 2031 · Found a bug? · Made with ♥ by Oliver Zehentleitner on &"
    )  # the year from the hub's clock, never a fixed one
    assert re.findall(r'<a href="([^"]+)"', line) == LINKS  # absolute, the Maity page without @
    assert line.count('target="_blank" rel="noopener noreferrer"') == 3
    assert 'aria-label="GitHub"' in line and 'aria-label="Maity"' in line
    assert '<span role="img" aria-label="love">♥</span>' in line
    # Three icons and the two separators, which are drawn, not read.
    assert line.count("<svg") == 3 and line.count('aria-hidden="true"') == 5
    assert line.count('<span aria-hidden="true"> · </span>') == 2
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


def test_the_link_pages_end_with_the_line() -> None:
    strict(email_sign_in._dead())
    page = bytes(register_page._dead().body).decode()
    assert 'class="product-line"' in page
    # Its policy allows its stylesheet: the line centred and muted, the mark follows a dark
    # theme there (§16.13).
    assert product_line.STYLE + product_line.DARK in page
    german = render.form_document(lang="de", title="t", content="", footer="")
    assert "Einen Fehler gefunden?" in german  # in the page's language


def test_a_mail_page_ends_with_the_line_in_its_language(
    make_client: ClientFactory, migrated: Engine
) -> None:
    client = make_client(mail=mail_hub().mail)
    assert "Found a bug?" in strict(client.get("/mail/unsubscribe/garbage"))
    human_id = factory.human(migrated, "maintainer")
    stored(migrated, human_id, {"email": {"language": "de"}})
    page = strict(client.get(f"/mail/unsubscribe/{link(human_id)}"))
    assert "Einen Fehler gefunden?" in page and "Found a bug?" not in page
    stored_dead = client.get(f"/mail/unsubscribe/{link(human_id, epoch=7)}")
    assert stored_dead.status_code == 404 and "Einen Fehler gefunden?" in strict(stored_dead)


def test_a_page_whose_words_the_language_lacks_has_an_english_line(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real = catalog.speaks
    monkeypatch.setattr(
        catalog, "speaks", lambda name, lang: False if name == "mail_links" else real(name, lang)
    )
    assert "Found a bug?" in product_line.html("de", "mail_links")
    assert "Einen Fehler gefunden?" in product_line.html("de", "sign_in")


def test_the_sign_in_link_page_ends_with_the_line_in_the_humans_language(
    make_client: ClientFactory, migrated: Engine
) -> None:
    client, human = setup(make_client, migrated)
    with migrated.begin() as conn:
        conn.execute(update(t.human).where(t.human.c.id == human).values(interface_language="de"))
    ask(client)
    url, _ = mail(migrated)
    page = strict(client.get(url))
    assert "Einen Fehler gefunden?" in page


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
