"""Site values and placeholders (docs/api.md §16.7.3): the pairs an instance admin keeps, and
no placeholder on any public text, whichever way it is written."""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine

from maity_hub.landing import LANGUAGES
from maity_hub.render import WORDS, choose_language
from tests import flow
from tests.conftest import ClientFactory
from tests.test_pages import ADMIN, hero

PATH = "/admin/settings/site-values"
LEGAL = "/admin/settings/legal"
REGISTRATION = "/admin/settings/registration"


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    return flow.human(make_client, migrated)


def fields(answer: Any) -> dict[str, str]:
    found: dict[str, str] = answer.json()["error"]["details"]["fields"]
    return found


def test_the_values_are_replaced_as_a_whole(owner: flow.Human) -> None:
    assert owner.get(PATH).json() == {"values": {}}
    saved = owner.patch(PATH, {"values": {"operator": "Example", "hosting_provider": "Host, Land"}})
    assert saved.status_code == 200, saved.text
    assert saved.json()["values"] == {"operator": "Example", "hosting_provider": "Host, Land"}
    assert owner.patch(PATH, {"values": {"operator": "Other"}}).json() == {
        "values": {"operator": "Other"}
    }
    assert owner.get(PATH).json() == {"values": {"operator": "Other"}}
    assert owner.patch(PATH, {"values": {}}).json() == {"values": {}}
    assert owner.get(PATH).json() == {"values": {}}


@pytest.mark.parametrize(
    "values, path, reason",
    [
        ({"Upper": "x"}, "values.Upper", "invalid"),
        ({"1st": "x"}, "values.1st", "invalid"),
        ({"a" * 41: "x"}, f"values.{'a' * 41}", "invalid"),
        ({"name": ""}, "values.name", "invalid"),
        ({"name": " x"}, "values.name", "invalid"),
        ({"name": "two\nlines"}, "values.name", "invalid"),
        ({"name": "x" * 501}, "values.name", "invalid"),
        ({"name": 5}, "values.name", "invalid"),
        ({"name": "see {{other}}"}, "values.name", "unresolved_placeholder"),
        ({f"n{i}": "x" for i in range(51)}, "values", "invalid"),
        ([], "values", "invalid"),
    ],
)
def test_a_bad_pair_is_refused_at_its_path(
    owner: flow.Human, values: Any, path: str, reason: str
) -> None:
    answer = owner.patch(PATH, {"values": values})
    assert answer.status_code == 400
    assert fields(answer) == {path: reason}
    assert owner.get(PATH).json() == {"values": {}}


def test_a_body_without_values_or_with_more_is_refused(owner: flow.Human) -> None:
    assert fields(owner.patch(PATH, {})) == {"values": "required"}
    assert fields(owner.patch(PATH, {"values": {}, "more": 1})) == {"more": "extra_forbidden"}


def test_only_an_instance_admin_reads_or_writes(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    stranger = flow.human(make_client, migrated, "stranger")
    assert stranger.get(PATH).status_code == 403
    assert stranger.patch(PATH, {"values": {"name": "x"}}).status_code == 403
    assert owner.get(PATH).json() == {"values": {}}


def test_an_agent_credential_is_refused_before_any_read(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    flow.project(owner)
    agent = flow.agent(make_client, owner)
    assert agent.get(PATH).status_code == 403
    assert agent.patch(PATH, {"values": {"name": "x"}}).status_code == 403


LEGAL_PAGE = {"en": {"title": "Imprint", "markdown": "Words."}}


@pytest.mark.parametrize(
    "text", ["By {{name}}", "By {{ name }}", "By {{Name}}", "{{hosting-provider}}"]
)
def test_a_legal_page_holding_a_placeholder_is_refused(owner: flow.Human, text: str) -> None:
    page = {"en": {"title": "Imprint", "markdown": text}}
    for answer in (
        owner.patch(LEGAL, {"imprint": page}),
        owner.post(f"{LEGAL}/preview?page=imprint", page),
    ):
        assert answer.status_code == 400
        assert fields(answer) == {"imprint.en.markdown": "unresolved_placeholder"}
    assert owner.patch(LEGAL, {"imprint": LEGAL_PAGE}).status_code == 200


@pytest.mark.parametrize("text", ["{{ .Values.host }}", "{{#if x}}", "{{1}}", "{ {name} }", "{{}}"])
def test_what_is_no_placeholder_stays_allowed(owner: flow.Human, text: str) -> None:
    page = {"en": {"title": "Imprint", "markdown": f"Quoted: `{text}`"}}
    answer = owner.patch(LEGAL, {"imprint": page})
    assert answer.status_code == 200, answer.text


def test_a_landing_page_holding_a_placeholder_is_refused_at_its_path(owner: flow.Human) -> None:
    pages = {"en": {"title": "{{name}}", "description": "", "sections": [hero()]}}
    footer = {"operator": "{{operator}}", "social": []}
    body = {"default_language": "en", "pages": pages, "footer": footer}
    for answer in (owner.patch(ADMIN, body), owner.post(f"{ADMIN}/preview", body)):
        assert answer.status_code == 400
        assert fields(answer) == {
            "pages.en.title": "unresolved_placeholder",
            "footer.operator": "unresolved_placeholder",
        }


def test_a_registration_setting_holding_a_placeholder_is_refused(owner: flow.Human) -> None:
    answer = owner.patch(
        REGISTRATION, {"terms": {"url": "https://example.org/{{name}}", "version": "1"}}
    )
    assert answer.status_code == 400
    assert "unresolved_placeholder" in fields(answer).values()


TEMPLATE = Path(__file__).resolve().parents[2] / "web" / "tools" / "maity-site.json"


def test_the_real_site_file_imports_in_every_language(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    """What the dashboard does: fill the placeholders, then each save, then read each page."""
    text = TEMPLATE.read_text(encoding="utf-8")
    values = {name: f"Example {name}" for name in set(re.findall(r"\{\{([a-z_]+)\}\}", text))}
    for name, value in values.items():
        text = text.replace("{{" + name + "}}", value)
    site = json.loads(text)
    assert set(site["landing"]["pages"]) == set(LANGUAGES)
    for page, one in site["legal"].items():
        assert set(one["languages"]) == set(LANGUAGES), page
        saved = owner.patch(LEGAL, {page: one["languages"]})
        assert saved.status_code == 200, saved.text
    saved = owner.patch(ADMIN, site["landing"])
    assert saved.status_code == 200, saved.text
    visitor = make_client()
    for tag in LANGUAGES:
        for address in ("/", "/impressum", "/privacy", "/terms"):
            page = visitor.get(address, params={"lang": tag})
            assert page.status_code == 200, f"{address} {tag}"
            assert f'<html lang="{tag}">' in page.text, f"{address} {tag}"
            assert "{{" not in page.text, f"{address} {tag}"


def test_every_language_of_the_site_file_has_the_same_placeholders() -> None:
    """A placeholder translated or lost in one language would still import, so each page is
    compared with its English text, repeats included, and only the known names count."""

    def names(text: object) -> Counter[str]:
        return Counter(re.findall(r"\{\{([^}]*)\}\}", json.dumps(text, ensure_ascii=False)))

    site = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    pages = {page: one["languages"] for page, one in site["legal"].items()}
    pages["landing"] = site["landing"]["pages"]
    seen: Counter[str] = names(site["landing"]["footer"])
    for page, languages in pages.items():
        for tag, text in languages.items():
            assert names(text) == names(languages["en"]), f"{page} {tag}"
        seen += names(languages["en"])
    assert set(seen) == {
        "address",
        "date",
        "email",
        "hosting_provider",
        "mail_provider",
        "name",
        "operator",
    }


def test_every_language_has_every_word_of_the_frame() -> None:
    assert set(WORDS) == set(LANGUAGES)
    for tag, words in WORDS.items():
        assert set(words) == set(WORDS["en"]), tag


@pytest.mark.parametrize(
    "header, expected",
    [
        ("zh-CN,zh;q=0.9", "zh-Hans"),
        ("zh-Hans", "zh-Hans"),
        ("zh", "zh-Hans"),
        ("zh-TW,ja;q=0.8", "ja"),
        ("zh-Hant-HK", "en"),
        ("ko-KR", "ko"),
        ("pt-BR,en;q=0.5", "pt"),
    ],
)
def test_the_browsers_language_finds_the_offered_one(header: str, expected: str) -> None:
    assert choose_language(list(LANGUAGES), "en", None, header) == expected
