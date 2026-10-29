"""docs/api.md §16.7, §16.7.1: a draft of the landing page or of a legal page, seen before it
is saved."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import Engine, func, select

from maity_hub import clock
from maity_hub import tables as t
from tests import factory, flow
from tests.conftest import ClientFactory

ADMIN = "/admin/settings/landing"
LEGAL = "/admin/settings/legal"
HERO = {
    "type": "hero",
    "enabled": True,
    "title": "A draft title",
    "cta_primary": {"label": "Go", "href": "/register"},
}
DRAFT = {"pages": {"en": {"title": "Draft", "description": "d", "sections": [HERO]}}}
TEXT = {"en": {"title": "Terms draft", "markdown": "Not yet **saved**."}}


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    return flow.human(make_client, migrated)  # the first human: the instance admin


def at(moment: Any) -> Any:
    return lambda: moment


def drafts(migrated: Engine) -> int:
    with migrated.connect() as conn:
        return int(conn.execute(select(func.count()).select_from(t.preview_draft)).scalar_one())


def open_draft(owner: flow.Human, body: dict[str, Any] | None = None) -> tuple[dict[str, Any], str]:
    made = owner.post(f"{ADMIN}/preview", body or DRAFT)
    assert made.status_code == 201, made.text
    found = made.json()
    return found, found["url"]


def test_a_draft_is_posted_then_opened_as_the_page_would_be(
    owner: flow.Human, migrated: Engine
) -> None:
    found, path = open_draft(owner)
    assert set(found) == {"id", "url", "expires_at"}
    assert found["url"] == f"/api/v1{ADMIN}/preview/{found['id']}"  # the path under the API base
    page = owner.client.get(path)
    assert page.status_code == 200 and page.headers["content-type"].startswith("text/html")
    assert page.headers["cache-control"] == "no-store" and page.headers["x-robots-tag"] == "noindex"
    assert page.headers["content-security-policy"].startswith("default-src 'none'; style-src")
    assert "<h1>A draft title</h1>" in page.text and "<script" not in page.text
    assert "Preview of an unsaved draft" in page.text
    # Nothing was saved: the setting is as it was, the root still says nothing of it.
    assert owner.get(ADMIN).json()["pages"] == {} and owner.get(ADMIN).json()["enabled"] is False


def test_a_draft_leaves_out_what_it_takes_from_the_saved_setting_and_ignores_enabled(
    owner: flow.Human,
) -> None:
    owner.patch(
        ADMIN,
        {
            "pages": {"en": {"title": "Saved", "sections": [HERO]}},
            "footer": {"operator": "Saved Operator"},
        },
    )
    _, path = open_draft(owner, {"enabled": False, "pages": DRAFT["pages"]})
    page = owner.client.get(path).text
    assert "Saved Operator" in page and "<title>Draft</title>" in page
    assert owner.get(ADMIN).json()["pages"]["en"]["title"] == "Saved"


def test_a_draft_is_validated_like_a_patch_and_needs_a_page_to_show(owner: flow.Human) -> None:
    bad = {"pages": {"en": {"title": "T", "sections": [{"type": "text", "enabled": True}]}}}
    refused = owner.post(f"{ADMIN}/preview", bad)
    assert refused.status_code == 400
    assert refused.json()["error"]["details"]["fields"] == {
        "pages.en.sections.0.markdown": "required"
    }
    nothing = owner.post(f"{ADMIN}/preview", {})
    assert nothing.json()["error"]["details"]["fields"] == {"pages.en": "required"}


def test_a_draft_belongs_to_the_session_that_posted_it(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    found, path = open_draft(owner)
    other = make_client()
    other.cookies.update(owner.client.cookies)  # the same account, signed in again elsewhere
    assert other.get(path).status_code == 200  # the same session cookie is the same session
    second_session = make_client()
    login = second_session.post(
        "/api/v1/auth/login", json={"handle": "maintainer", "password": factory.PASSWORD}
    )
    assert login.status_code == 200, login.text
    assert second_session.get(path).status_code == 404  # another session: not found
    assert make_client().get(path).status_code == 401


def test_an_expired_or_unknown_draft_is_not_found(owner: flow.Human) -> None:
    found, path = open_draft(owner)
    assert owner.client.get(path.replace(found["id"], "nope")).status_code == 404
    clock.set_source(at(clock.now() + timedelta(minutes=10, seconds=1)))
    assert owner.client.get(path).status_code == 404


def test_a_session_keeps_twenty_drafts_and_the_oldest_goes(
    owner: flow.Human, migrated: Engine
) -> None:
    start = clock.now()
    paths = []
    for n in range(21):
        clock.set_source(at(start + timedelta(seconds=n)))
        paths.append(open_draft(owner)[1])
    assert drafts(migrated) == 20
    assert owner.client.get(paths[0]).status_code == 404
    assert owner.client.get(paths[1]).status_code == 200


def test_only_the_instance_admin_posts_or_opens_a_draft(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    _, path = open_draft(owner)
    other = flow.human(make_client, migrated, "someone")
    assert other.post(f"{ADMIN}/preview", DRAFT).status_code == 403
    assert other.client.get(path).status_code in (403, 404)


# --- a draft of a legal page ----------------------------------------------------------------------


def test_a_legal_draft_says_draft_where_the_page_says_as_of_and_lists_no_versions(
    owner: flow.Human, migrated: Engine
) -> None:
    owner.patch(LEGAL, {"terms": {"en": {"title": "Terms 1", "markdown": "one"}}})
    made = owner.post(f"{LEGAL}/preview?page=terms", TEXT)
    assert made.status_code == 201, made.text
    path = made.json()["url"]
    page = owner.client.get(path)
    assert page.status_code == 200
    assert (
        page.headers["content-security-policy"] == "default-src 'none'; style-src 'unsafe-inline'"
    )
    assert page.headers["cache-control"] == "no-store" and page.headers["x-robots-tag"] == "noindex"
    assert (
        "<h1>Terms draft</h1>" in page.text
        and "Draft" in page.text
        and "<strong>saved</strong>" in page.text
    )
    assert "As of" not in page.text and "Earlier versions" not in page.text
    assert owner.get(LEGAL).json()["pages"]["terms"]["languages"]["en"]["title"] == "Terms 1"


def test_a_legal_draft_takes_the_languages_alone_and_counts_no_limit(owner: flow.Human) -> None:
    for _ in range(25):  # no change limit applies to a preview (§16.7.1)
        assert owner.post(f"{LEGAL}/preview?page=privacy", TEXT).status_code == 201
    assert owner.get(LEGAL).json()["pages"]["privacy"] is None
    wrapped = owner.post(f"{LEGAL}/preview?page=privacy", {"privacy": TEXT})  # not the PATCH value
    assert wrapped.status_code == 400
    assert wrapped.json()["error"]["details"]["fields"] == {"privacy.privacy": "invalid"}


@pytest.mark.parametrize(
    ("query", "body", "field"),
    [
        ("", TEXT, "page"),
        ("?page=nope", TEXT, "page"),
        ("?page=terms", {"fr": TEXT["en"]}, "terms.fr"),
        ("?page=terms", {"en": {"title": "T", "markdown": "<b>x"}}, "terms.en.markdown"),
        ("?page=terms", {}, "terms"),
    ],
)
def test_a_legal_draft_is_validated_like_a_patch(
    owner: flow.Human, query: str, body: dict[str, Any], field: str
) -> None:
    refused = owner.post(f"{LEGAL}/preview{query}", body)
    assert refused.status_code == 400
    assert field in refused.json()["error"]["details"]["fields"]


def test_a_draft_is_shown_in_its_default_language_not_the_browsers(owner: flow.Human) -> None:
    both = {
        "default_language": "de",
        "pages": {
            "en": {"title": "English draft", "sections": [HERO]},
            "de": {"title": "Deutscher Entwurf", "sections": [HERO]},
        },
    }
    _, path = open_draft(owner, both)
    german = owner.client.get(path, headers={"Accept-Language": "en"})
    assert "<title>Deutscher Entwurf</title>" in german.text  # `Accept-Language` is not read
    assert "<title>English draft</title>" in owner.client.get(f"{path}?lang=en").text
    assert "<title>Deutscher Entwurf</title>" in owner.client.get(f"{path}?lang=fr").text


def test_a_draft_may_be_as_large_as_the_setting_it_previews(owner: flow.Human) -> None:
    """§16.7: the 512 KiB cap of the PATCH holds for the two preview POSTs; past it is 413."""
    wide = {"type": "text", "enabled": True, "markdown": "x" * (300 * 1024)}
    fits = owner.post(f"{ADMIN}/preview", {"pages": {"en": {"title": "T", "sections": [wide]}}})
    assert fits.status_code == 400  # past the stored 256 KiB: invalid, not too large
    assert fits.json()["error"]["code"] == "invalid"
    huge = {"type": "text", "enabled": True, "markdown": "x" * (513 * 1024)}
    over = owner.post(f"{ADMIN}/preview", {"pages": {"en": {"title": "T", "sections": [huge]}}})
    assert (over.status_code, over.json()["error"]["code"]) == (413, "payload_too_large")
    legal = owner.post(
        f"{LEGAL}/preview?page=terms", {"en": {"title": "T", "markdown": "x" * (513 * 1024)}}
    )
    assert (legal.status_code, legal.json()["error"]["code"]) == (413, "payload_too_large")
