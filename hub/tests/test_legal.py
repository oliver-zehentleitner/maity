"""docs/api.md §16.7.1: the legal pages, their versions and the unauthenticated read."""

from __future__ import annotations

import re
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import Engine, func, select

from maity_hub import clock
from maity_hub import tables as t
from tests import flow
from tests.conftest import ClientFactory

PATH = "/admin/settings/legal"
EN = {"en": {"title": "Imprint", "markdown": "# Operator\n\nMaity, Austria. [Contact](/login)"}}
DE = {"de": {"title": "Impressum", "markdown": "Betreiber: Maity"}}
VERSION = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    return flow.human(make_client, migrated)  # the first human: the instance admin


def field(response: Any) -> Any:
    return response.json()["error"]["details"]["fields"]


@pytest.fixture
def moved() -> Any:
    """The clock, moved by whole seconds from where the test began."""
    start = clock.now().replace(microsecond=0)
    clock.set_source(lambda: start)

    def move(**delta: float) -> None:
        moment = start + timedelta(**delta)
        clock.set_source(lambda: moment)

    return move


def test_nothing_is_set_by_default(owner: flow.Human, make_client: ClientFactory) -> None:
    assert owner.get(PATH).json() == {
        "default_language": "en",
        "pages": {"imprint": None, "privacy": None, "terms": None},
        "updated_at": None,
        "updated_by": None,
    }
    answer = make_client().get("/api/v1/legal")
    assert (answer.status_code, answer.json()) == (200, {"default_language": "en", "pages": {}})
    assert answer.headers["cache-control"] == "public, max-age=60"


def test_a_page_is_replaced_as_a_whole_and_gets_a_version(
    owner: flow.Human, make_client: ClientFactory, moved: Any
) -> None:
    first = owner.patch(PATH, {"imprint": {**EN, **DE}})
    assert first.status_code == 200, first.text
    page = first.json()["pages"]["imprint"]
    assert VERSION.fullmatch(page["version"]) and page["versions"] == []
    assert page["languages"] == {**EN, **DE}
    assert first.json()["updated_by"] == owner.id
    moved(minutes=1)
    second = owner.patch(PATH, {"imprint": EN})
    again = second.json()["pages"]["imprint"]
    assert again["languages"] == EN  # the German text is gone from the page, not from the record
    assert again["versions"] == [page["version"]] and again["version"] > page["version"]
    shown = make_client().get("/api/v1/legal").json()
    assert shown["pages"] == {"imprint": {"version": again["version"], "languages": ["en"]}}
    assert "markdown" not in str(shown)


def test_two_changes_in_one_second_get_two_versions(owner: flow.Human, moved: Any) -> None:
    owner.patch(PATH, {"terms": EN})
    owner.patch(PATH, {"terms": DE})
    page = owner.get(PATH).json()["pages"]["terms"]
    assert len(page["versions"]) == 1 and page["version"] > page["versions"][0]


def test_an_unset_page_keeps_its_versions(owner: flow.Human, migrated: Engine) -> None:
    owner.patch(PATH, {"privacy": EN})
    unset = owner.patch(PATH, {"privacy": None})
    assert unset.status_code == 200 and unset.json()["pages"]["privacy"] is None
    with migrated.connect() as conn:
        kept = conn.execute(
            select(func.count())
            .select_from(t.legal_version)
            .where(t.legal_version.c.page == "privacy")
        ).scalar_one()
    assert kept == 1
    owner.patch(PATH, {"privacy": DE})  # set again: a new version, the old one is an earlier one
    assert len(owner.get(PATH).json()["pages"]["privacy"]["versions"]) == 1


def test_the_default_language_goes_alone_or_with_one_page(owner: flow.Human) -> None:
    assert owner.patch(PATH, {"default_language": "de"}).json()["default_language"] == "de"
    both = owner.patch(PATH, {"default_language": "en", "terms": EN})
    assert both.status_code == 200 and both.json()["default_language"] == "en"
    assert both.json()["pages"]["terms"]["languages"] == EN


@pytest.mark.parametrize(
    ("body", "fields"),
    [
        ({}, {"body": "empty"}),
        ({"imprint": EN, "terms": EN}, {"terms": "one_page_per_call"}),
        ({"nope": EN}, {"nope": "extra_forbidden"}),
        ({"default_language": "fr"}, {"default_language": "invalid"}),
        ({"imprint": {}}, {"imprint": "invalid"}),
        ({"imprint": "text"}, {"imprint": "invalid"}),
        ({"imprint": {"fr": EN["en"]}}, {"imprint.fr": "invalid"}),
        ({"imprint": {"en": {"markdown": "x"}}}, {"imprint.en.title": "required"}),
        ({"imprint": {"en": {"title": "T"}}}, {"imprint.en.markdown": "required"}),
        ({"imprint": {"en": {"title": "", "markdown": "x"}}}, {"imprint.en.title": "invalid"}),
        (
            {"imprint": {"en": {"title": "x" * 121, "markdown": "x"}}},
            {"imprint.en.title": "invalid"},
        ),
        (
            {"imprint": {"en": {"title": "T", "markdown": "x", "zz": 1}}},
            {"imprint.en.zz": "extra_forbidden"},
        ),
        (
            {"imprint": {"en": {"title": "T", "markdown": "<b>x"}}},
            {"imprint.en.markdown": "line 1"},
        ),
        (
            {"imprint": {"en": {"title": "T", "markdown": "![i](https://x.example/i.png)"}}},
            {"imprint.en.markdown": "line 1"},
        ),
        (
            {"imprint": {"en": {"title": "T", "markdown": "a\x01b"}}},
            {"imprint.en.markdown": "control_character"},
        ),
        (
            {"imprint": {"en": {"title": "T", "markdown": "x" * (64 * 1024 + 1)}}},
            {"imprint.en.markdown": "invalid"},
        ),
    ],
)
def test_what_a_page_may_not_hold_is_named_by_its_path(
    owner: flow.Human, body: dict[str, Any], fields: dict[str, str]
) -> None:
    refused = owner.patch(PATH, body)
    assert refused.status_code == 400, refused.text
    assert field(refused) == fields


def test_a_page_at_the_text_limit_passes(owner: flow.Human) -> None:
    full = {"en": {"title": "T" * 120, "markdown": "é" * (32 * 1024)}}
    saved = owner.patch(PATH, {"terms": full})
    assert saved.status_code == 200, saved.text


def test_the_twenty_first_change_of_a_page_in_a_day_is_refused(
    owner: flow.Human, moved: Any
) -> None:
    for second in range(20):
        moved(seconds=second)
        assert owner.patch(PATH, {"terms": EN}).status_code == 200, second
    moved(seconds=20)
    refused = owner.patch(PATH, {"terms": EN})
    assert (refused.status_code, refused.json()["error"]["code"]) == (429, "rate_limited")
    assert owner.patch(PATH, {"privacy": EN}).status_code == 200  # another page has its own count
    moved(hours=25)
    assert owner.patch(PATH, {"terms": EN}).status_code == 200


def test_only_the_instance_admin_edits_them(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    other = flow.human(make_client, migrated, "someone")
    assert other.get(PATH).status_code == 403
    assert other.patch(PATH, {"imprint": EN}).status_code == 403
    assert make_client().get(f"/api/v1{PATH}").status_code == 401


def test_the_larger_cap_is_the_settings_alone(owner: flow.Human) -> None:
    big = owner.patch(PATH, {"imprint": {"en": {"title": "T", "markdown": "x" * (513 * 1024)}}})
    assert (big.status_code, big.json()["error"]["code"]) == (413, "payload_too_large")


def test_the_public_read_has_an_etag_that_follows(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    visitor = make_client()
    empty = visitor.get("/api/v1/legal").headers["etag"]
    owner.patch(PATH, {"terms": EN})
    answer = visitor.get("/api/v1/legal")
    assert answer.headers["etag"] != empty
    assert (
        visitor.get("/api/v1/legal", headers={"If-None-Match": answer.headers["etag"]}).status_code
        == 304
    )
