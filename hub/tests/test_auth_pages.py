"""docs/api.md §16.7.4: the pitch of the sign-in and sign-up pages, per language."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import Engine

from tests import flow
from tests.conftest import ClientFactory
from tests.test_join_host import join_client

PATH = "/admin/settings/auth-pages"
PUBLIC = "/api/v1/auth/pages/sign_in"


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    return flow.human(make_client, migrated)


def fields(answer: Any) -> dict[str, str]:
    assert answer.status_code == 400
    found: dict[str, str] = answer.json()["error"]["details"]["fields"]
    return found


def body(**texts: Any) -> dict[str, Any]:
    return {"pages": {"sign_in": {"de": texts}}}


def test_without_a_setting_the_defaults_answer(owner: flow.Human) -> None:
    assert owner.get(PATH).json() == {
        "default_language": "en",
        "pages": {"sign_in": {}, "sign_up": {}},
        "updated_at": None,
        "updated_by": None,
    }


def test_a_patch_replaces_the_setting_as_a_whole_and_stores_a_text_trimmed(
    owner: flow.Human,
) -> None:
    first = owner.patch(PATH, {"default_language": "de", **body(title="  Hallo  ", note="*Na*")})
    assert first.status_code == 200
    saved = first.json()
    assert saved["pages"]["sign_in"]["de"] == {"title": "Hallo", "note": "*Na*"}
    assert saved["updated_at"] and saved["updated_by"]
    assert owner.get(PATH).json() == saved
    again = owner.patch(PATH, {"pages": {"sign_up": {"en": {"title": "Join"}}}}).json()
    assert again["default_language"] == "en" and again["pages"]["sign_in"] == {}


@pytest.mark.parametrize(
    ("written", "path", "reason"),
    [
        ({"more": 1}, "more", "extra_forbidden"),
        ({"default_language": ["en"]}, "default_language", "invalid"),
        ({"default_language": "xx"}, "default_language", "invalid"),
        ({"pages": {"other": {}}}, "pages.other", "extra_forbidden"),
        ({"pages": {"sign_in": {"xx": {}}}}, "pages.sign_in.xx", "invalid"),
        (body(submit="Go"), "pages.sign_in.de.submit", "extra_forbidden"),
        (body(title="   "), "pages.sign_in.de.title", "invalid"),
        (body(title="a\nb"), "pages.sign_in.de.title", "invalid"),
        (body(title="a b"), "pages.sign_in.de.title", "invalid"),
        (body(title="a\x07b"), "pages.sign_in.de.title", "invalid"),
        (body(title="x" * 501), "pages.sign_in.de.title", "invalid"),
        (body(title=1), "pages.sign_in.de.title", "invalid"),
        (body(note="ä" * 2049), "pages.sign_in.de.note", "invalid"),
        (body(note="<b>x</b>"), "pages.sign_in.de.note", "invalid"),
        (body(title="{{ name }}"), "pages.sign_in.de.title", "unresolved_placeholder"),
        (body(note="{{name}}"), "pages.sign_in.de.note", "unresolved_placeholder"),
    ],
)
def test_patch_and_check_refuse_the_same_way(
    owner: flow.Human, written: dict[str, Any], path: str, reason: str
) -> None:
    assert fields(owner.patch(PATH, written)) == {path: reason}
    assert fields(owner.post(f"{PATH}/check", written)) == {path: reason}


def test_check_stores_nothing(owner: flow.Human) -> None:
    assert owner.post(f"{PATH}/check", body(title="Hallo")).status_code == 204
    assert owner.get(PATH).json()["pages"]["sign_in"] == {}


def test_a_visitor_gets_only_the_chosen_language(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    owner.patch(
        PATH,
        {
            "pages": {
                "sign_in": {
                    "en": {"title": "Hello", "subline": "Sign in"},
                    "de": {"title": "Hallo"},
                    "fr": {},
                }
            }
        },
    )
    visitor = make_client()
    german = visitor.get(f"{PUBLIC}?lang=de")
    assert german.json() == {"language": "de", "texts": {"title": "Hallo"}}  # no English subline
    assert german.headers["cache-control"] == "public, max-age=60"
    assert german.headers["vary"] == "Accept-Language"
    again = visitor.get(f"{PUBLIC}?lang=de", headers={"If-None-Match": german.headers["etag"]})
    assert again.status_code == 304
    by_header = visitor.get(PUBLIC, headers={"Accept-Language": "de-AT, en;q=0.5"})
    assert by_header.json()["language"] == "de"
    assert visitor.get(f"{PUBLIC}?lang=xx").json()["language"] == "en"  # no error
    # A language without a key is not this page's.
    assert visitor.get(f"{PUBLIC}?lang=fr").json()["language"] == "en"


def test_a_page_without_text_in_the_default_language_is_empty_not_another_language(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    owner.patch(PATH, body(title="Hallo"))
    answer = make_client().get(PUBLIC, headers={"Accept-Language": "fr"})
    assert answer.status_code == 200 and answer.json() == {"language": "en", "texts": {}}
    assert make_client().get("/api/v1/auth/pages/sign_up").json()["texts"] == {}
    assert make_client().get("/api/v1/auth/pages/other").status_code == 404


def test_only_an_admin_with_a_session_reaches_the_setting(
    make_client: ClientFactory, owner: flow.Human, migrated: Engine
) -> None:
    other = flow.human(make_client, migrated, "someone")
    assert other.get(PATH).status_code == 403
    assert other.patch(PATH, {}).status_code == 403
    assert other.post(f"{PATH}/check", {}).status_code == 403
    assert make_client().get(f"/api/v1{PATH}").status_code == 401


def test_a_large_body_is_taken(owner: flow.Human) -> None:
    texts = {f"point_{n}": "x" * 500 for n in (1, 2, 3)} | {
        "title": "x" * 500,
        "subline": "y" * 500,
    }
    languages = {tag: texts for tag in ("en", "de", "fr", "es", "pt", "it", "nl", "ja", "ko")}
    pages = {"sign_in": languages, "sign_up": languages}
    assert owner.post(f"{PATH}/check", {"pages": pages}).status_code == 204


def test_the_join_host_never_serves_it(owner: flow.Human, make_client: ClientFactory) -> None:
    owner.patch(PATH, body(title="Hallo"))
    answer = join_client(make_client).get(f"{PUBLIC}?lang=de", follow_redirects=False)
    assert answer.status_code in (302, 404) and "Hallo" not in answer.text
