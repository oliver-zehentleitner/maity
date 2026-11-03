"""docs/api.md §16.13: the product line at the end of the hub's own pages, and no referrer on a
page with a token in its path."""

from __future__ import annotations

import re
from html import unescape
from typing import Any

import pytest

from maity_hub import catalog, clock, maintenance, product_line, render
from maity_hub.routes import email_sign_in, register_page
from tests import flow
from tests.conftest import ClientFactory
from tests.test_join_host import create, join_client, token_of

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
    line = product_line.html("en")
    assert (
        text_of(line)
        == (
            f"Maity {clock.now().year} · Found a bug? · Made with ♥ by Oliver Zehentleitner on & "
        ).strip()
    )
    assert re.findall(r'<a href="([^"]+)"', line) == LINKS  # absolute, the Maity page without @
    assert line.count('target="_blank" rel="noopener noreferrer"') == 3
    assert 'aria-label="GitHub"' in line and 'aria-label="Maity"' in line
    assert '<span role="img" aria-label="love">♥</span>' in line
    assert line.count("<svg") == 3 and line.count('aria-hidden="true"') == 3
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


def test_the_maintenance_page_ends_with_the_line() -> None:
    found: dict[str, Any] = {"until": "2026-11-03T12:00:00Z", "text": "Upgrade"}
    page = bytes(maintenance.refusal_page(found).body).decode()
    assert page.index("</main>") < page.index('class="product-line"') < page.index("</body>")


def test_the_link_pages_end_with_the_line() -> None:
    assert 'class="product-line"' in bytes(email_sign_in._dead().body).decode()
    page = bytes(register_page._dead().body).decode()
    assert 'class="product-line"' in page
    # Its policy allows its stylesheet: the mark follows a dark theme there.
    assert product_line.DARK_STYLE in page
    assert 'class="product-line"' in render.form_document(
        lang="de", title="t", content="", footer=""
    )


def test_a_mail_page_ends_with_the_line_in_its_language(make_client: ClientFactory) -> None:
    page = make_client().get("/mail/unsubscribe/garbage")
    assert page.status_code == 404 and 'class="product-line"' in page.text
    assert page.headers["Referrer-Policy"] == "no-referrer"


def test_the_join_page_in_a_browser_ends_with_the_line_and_sends_no_referrer(
    make_client: ClientFactory, owner: flow.Human
) -> None:
    token = token_of(create(owner))
    html = join_client(make_client).get(f"/{token}", headers={"Accept": "text/html"})
    assert 'class="product-line"' in html.text
    assert html.headers["Referrer-Policy"] == "no-referrer"
    public = make_client().get(f"/join/{token}", headers={"Accept": "text/html"})
    assert 'class="product-line"' in public.text
    assert public.headers["Referrer-Policy"] == "no-referrer"
    # The agent's Markdown answer carries no line (§16.13).
    markdown = make_client().get(f"/join/{token}")
    assert "product-line" not in markdown.text and "Found a bug?" not in markdown.text
