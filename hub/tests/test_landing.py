"""docs/api.md §16.7: the instance's landing page, in sections."""

# ruff: noqa: E501  (the parametrized sections are one case per line)

from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest
from sqlalchemy import Engine, delete

from maity_hub import landing
from maity_hub import tables as t
from maity_hub.errors import ApiError
from tests import flow
from tests.conftest import ClientFactory
from tests.test_join_host import join_client

ADMIN_PATH = "/admin/settings/landing"
OFF = {
    "enabled": False,
    "default_language": "en",
    "pages": {},
    "footer": {"operator": None, "social": []},
}
GOOD = "# Bring your own agent\n\nRead [the docs](https://example.com/docs) or [sign in](/login)."
HERO = {
    "type": "hero",
    "enabled": True,
    "title": "Bring your agents. Share one project.",
    "cta_primary": {"label": "Create your account", "href": "/register"},
}


def page(*sections: dict[str, Any], title: str = "Maity") -> dict[str, Any]:
    return {"title": title, "description": "A hub", "sections": list(sections)}


def text(markdown: str) -> dict[str, Any]:
    return {"type": "text", "enabled": True, "markdown": markdown}


def body(*sections: dict[str, Any], enabled: bool = False) -> dict[str, Any]:
    return {"enabled": enabled, "pages": {"en": page(*sections)}}


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    return flow.human(make_client, migrated)  # the first human: the instance admin


def field(response: Any) -> Any:
    return response.json()["error"]["details"]["fields"]


def public(client: Any, **headers: str) -> Any:
    return client.get("/api/v1/landing", headers=headers)


def test_disabled_by_default_and_the_same_for_everyone(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    visitor = make_client()
    answer = public(visitor)
    assert (answer.status_code, answer.json()) == (200, {"enabled": False})
    assert answer.headers["cache-control"] == "public, max-age=60"
    assert public(owner.client).json() == {"enabled": False}  # signed in or not
    got = owner.get(ADMIN_PATH).json()
    assert got == {**OFF, "updated_at": None, "updated_by": None}


def test_the_admin_publishes_it_and_the_etag_follows(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    visitor = make_client()
    off_tag = public(visitor).headers["etag"]
    footer = {
        "operator": "Maity, Austria",
        "social": [{"label": "Mastodon", "href": "https://m.example/@x"}],
    }
    saved = owner.patch(
        ADMIN_PATH,
        {**body(HERO, text(GOOD), enabled=True), "default_language": "en", "footer": footer},
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["updated_by"] == owner.id and saved.json()["updated_at"]
    shown = public(visitor)
    assert shown.json() == {
        "enabled": True,
        "default_language": "en",
        "pages": {"en": page(HERO, text(GOOD))},
        "footer": footer,
        "updated_at": saved.json()["updated_at"],
    }
    tag = shown.headers["etag"]
    assert tag != off_tag
    assert public(visitor, **{"If-None-Match": tag}).status_code == 304
    assert public(visitor, **{"If-None-Match": off_tag}).status_code == 200
    owner.patch(ADMIN_PATH, {"enabled": False})
    disabled = public(visitor, **{"If-None-Match": tag})
    assert (disabled.status_code, disabled.json()) == (200, {"enabled": False})


def test_a_field_named_replaces_the_stored_one_and_the_rest_stays(owner: flow.Human) -> None:
    owner.patch(ADMIN_PATH, {**body(text(GOOD)), "default_language": "de"})
    owner.patch(ADMIN_PATH, {"footer": {"operator": "Op"}})
    got = owner.get(ADMIN_PATH).json()
    assert got["default_language"] == "de" and got["pages"]["en"]["sections"][0]["markdown"] == GOOD
    assert got["footer"] == {"operator": "Op", "social": []}


@pytest.mark.parametrize(
    "markdown",
    [
        "fine\n<script>alert(1)</script>",
        "a <b>bold</b> word",
        "<!-- hidden -->",
        "![logo](https://example.com/logo.png)",
        "[x](http://example.com)",
        "[x](javascript:alert(1))",
        "[x](data:text/html,hi)",
        "[x](//evil.example)",
        "[x](https://user:pass@example.com)",
        "[x](https:/example.com)",
        "[x](https//example.com)",
        "[x](/#evil)",
        "[x](//evil.example/x)",
        "see https://user@evil.example/",
        "[x](https://[example.com)",  # no parse: invalid, never a 500
        "[x](https://example.com:bad/)",
        "[x](https://example.com:99999/)",
        "see https://[example.com/",
        # Fences as the dashboard reads them (`web/js/markdown.js`): a backtick opener
        # whose info string holds a backtick is no fence, so the next line is checked;
        # a closer with more than whitespace after it does not close.
        "```bad`info\n<script>x</script>",
        "````\ncode\n```\n<b>still code</b>\n````\n<b>",
        "```\ncode\n``` not a close\n```\n<b>",
        "~~~\ncode\n```\n~~~\n<b>",
        "    ```\n<b>",  # four spaces in: indented, no fence
    ],
)
def test_what_the_markdown_may_not_hold(owner: flow.Human, markdown: str) -> None:
    refused = owner.patch(ADMIN_PATH, body(text(markdown)))
    assert refused.status_code == 400, markdown
    assert field(refused)["pages.en.sections.0.markdown"].startswith("line ")


def test_html_in_fenced_code_is_text(owner: flow.Human) -> None:
    fenced = "Install:\n\n```html\n<script>not run</script>\n```\n\nThen [sign in](/login)."
    assert owner.patch(ADMIN_PATH, body(text(fenced))).status_code == 200
    second = owner.patch(ADMIN_PATH, body(text("one\n\nline three <b>")))
    assert field(second) == {"pages.en.sections.0.markdown": "line 3"}


@pytest.mark.parametrize(
    "markdown",
    [
        "```\n<b>never closed: code to the end</b>",
        "~~~ html\n<script></script>\n~~~   \nafter",
        "````\n```\n<b></b>\n`````\nafter",
        "a\r\n```\r\n<b></b>\r\n```\r\nafter",
        "[ok](https://example.com:8443/docs)",
    ],
)
def test_what_the_markdown_may_hold(owner: flow.Human, markdown: str) -> None:
    saved = owner.patch(ADMIN_PATH, body(text(markdown)))
    assert saved.status_code == 200, (markdown, saved.text)


def test_a_page_at_the_stored_limit_passes_the_body_cap(owner: flow.Human) -> None:
    """§16.7: a body whose JSON escaping grows it on the wire is accepted up to 512 KiB, a
    page past the stored 256 KiB is `invalid`, a body past 512 KiB is 413."""
    # 16 KiB of Markdown per text section, each a two-byte character escaped as `\\u00e9`.
    wide = "é" * (16 * 1024 // 2)
    sections = [text(wide) for _ in range(8)]
    raw = json.dumps(body(*sections), ensure_ascii=True)
    assert len(raw) > 64 * 1024
    sent = owner.client.patch(
        f"/api/v1{ADMIN_PATH}",
        content=raw,
        headers={"X-CSRF-Token": owner.csrf, "Content-Type": "application/json"},
    )
    assert sent.status_code == 200, sent.text
    huge = owner.patch(ADMIN_PATH, {"pages": {"en": page(text("x" * (513 * 1024)))}})
    assert (huge.status_code, huge.json()["error"]["code"]) == (413, "payload_too_large")


def test_the_stored_setting_is_capped(owner: flow.Human) -> None:
    """20 text sections of 16 KiB are 320 KiB on the wire, under the 512 KiB of the body and
    over the 256 KiB the setting may hold."""
    full = [text("x" * (16 * 1024)) for _ in range(20)]
    refused = owner.patch(ADMIN_PATH, body(*full))
    assert refused.status_code == 400
    assert field(refused) == {"pages": "too_large"}


@pytest.mark.parametrize(
    ("patch", "fields"),
    [
        (
            {"pages": {"en": page(text("a\x01b"))}},
            {"pages.en.sections.0.markdown": "control_character"},
        ),
        ({"pages": {"en": page(title="a\x00b")}}, {"pages.en.title": "control_character"}),
        (
            {"footer": {"operator": "O\x07p"}},
            {"footer.operator": "control_character"},
        ),
    ],
)
def test_control_characters_are_refused(
    owner: flow.Human, patch: dict[str, Any], fields: dict[str, str]
) -> None:
    assert field(owner.patch(ADMIN_PATH, patch)) == fields


def test_tab_newline_and_carriage_return_are_text(owner: flow.Human) -> None:
    saved = owner.patch(ADMIN_PATH, body(text("# Head\r\n\n\tindented\n")))
    assert saved.status_code == 200, saved.text


def test_the_larger_cap_is_the_settings_alone(owner: flow.Human) -> None:
    refused = owner.patch("/me", {"display_name": "x" * (65 * 1024)})
    assert refused.status_code == 413


def test_the_markdown_is_capped_in_bytes() -> None:
    """16 KiB of UTF-8 in a `text` section: a four-byte character counts four times."""
    fits = "\U0001f984" * (16 * 1024 // 4)
    stored = landing.check(body(text(fits)), OFF)
    assert stored["pages"]["en"]["sections"][0]["markdown"] == fits
    with pytest.raises(ApiError) as over:
        landing.check(body(text(fits + "x")), OFF)
    assert over.value.details == {"fields": {"pages.en.sections.0.markdown": "invalid"}}


ALL_TYPES = [
    HERO,
    {"type": "stats", "enabled": True, "items": ["people", "agents_online"]},
    {
        "type": "steps",
        "enabled": True,
        "title": "How",
        "items": [{"title": "a", "text": "b", "code": "c"}],
    },
    {
        "type": "scales",
        "enabled": False,
        "title": "Scales",
        "items": [{"tag": "t", "title": "a", "text": "b", "points": ["p1", "p2"]}],
    },
    {
        "type": "faq",
        "enabled": True,
        "title": "FAQ",
        "items": [{"q": "Why?", "a": "Because [here](/login)."}],
    },
    {"type": "cta_band", "enabled": True, "title": "Go", "cta": {"label": "Go", "href": "/login"}},
    text(GOOD),
    {"type": "activity", "enabled": False, "count": 5},
    {"type": "profiles", "enabled": True, "title": "People", "handles": ["ada"], "markdown": "hi"},
    {"type": "explore", "enabled": True, "title": "Explore", "projects": ["ada/maity"]},
    {
        "type": "collab",
        "enabled": False,
        "items": [
            {"tag": "a", "title": "b", "points": ["x"], "cta": {"label": "l", "href": "/new"}},
            {"tag": "c", "title": "d", "cta": {"label": "l", "href": "https://example.com"}},
        ],
    },
]


def test_every_section_type_is_stored_as_written(owner: flow.Human) -> None:
    saved = owner.patch(ADMIN_PATH, body(*ALL_TYPES))
    assert saved.status_code == 200, saved.text
    assert saved.json()["pages"]["en"]["sections"] == ALL_TYPES


@pytest.mark.parametrize(
    ("sections", "path", "reason"),
    [
        ([{"type": "nope", "enabled": True}], "pages.en.sections.0.type", "invalid"),
        ([{"type": "text", "markdown": "x"}], "pages.en.sections.0.enabled", "required"),
        (
            [{"type": "text", "enabled": 1, "markdown": "x"}],
            "pages.en.sections.0.enabled",
            "invalid",
        ),
        (
            [{"type": "text", "enabled": True, "markdown": "x", "zz": 1}],
            "pages.en.sections.0.zz",
            "extra_forbidden",
        ),
        (
            [{"type": "hero", "enabled": True, "title": "x"}],
            "pages.en.sections.0.cta_primary",
            "required",
        ),
        (
            [
                {
                    "type": "hero",
                    "enabled": True,
                    "title": "x" * 121,
                    "cta_primary": {"label": "a", "href": "/x"},
                }
            ],
            "pages.en.sections.0.title",
            "invalid",
        ),
        (
            [
                {
                    "type": "hero",
                    "enabled": True,
                    "title": "x",
                    "cta_primary": {"label": "a", "href": "http://x.com"},
                }
            ],
            "pages.en.sections.0.cta_primary.href",
            "invalid",
        ),
        (
            [{"type": "stats", "enabled": True, "items": ["people", "nope"]}],
            "pages.en.sections.0.items",
            "invalid",
        ),
        ([{"type": "stats", "enabled": True, "items": []}], "pages.en.sections.0.items", "invalid"),
        (
            [
                {
                    "type": "steps",
                    "enabled": True,
                    "items": [{"title": "a", "text": "b"}, {"title": "x" * 81, "text": "b"}],
                }
            ],
            "pages.en.sections.0.items.1.title",
            "invalid",
        ),
        ([{"type": "steps", "enabled": True, "items": []}], "pages.en.sections.0.items", "invalid"),
        (
            [{"type": "steps", "enabled": True, "items": [{"title": "a", "text": "b"}] * 7}],
            "pages.en.sections.0.items",
            "invalid",
        ),
        (
            [{"type": "faq", "enabled": True, "items": [{"q": "q", "a": "<b>x"}]}],
            "pages.en.sections.0.items.0.a",
            "line 1",
        ),
        (
            [{"type": "activity", "enabled": True, "count": 21}],
            "pages.en.sections.0.count",
            "invalid",
        ),
        (
            [{"type": "profiles", "enabled": True, "handles": ["a", "b", "c"]}],
            "pages.en.sections.0.handles",
            "invalid",
        ),
        (
            [{"type": "explore", "enabled": True, "projects": ["not-a-full-name"]}],
            "pages.en.sections.0.projects",
            "invalid",
        ),
        (
            [
                {
                    "type": "collab",
                    "enabled": True,
                    "items": [{"tag": "a", "title": "b", "cta": {"label": "l", "href": "/x"}}],
                }
            ],
            "pages.en.sections.0.items",
            "invalid",
        ),
    ],
)
def test_a_section_that_breaks_a_rule_is_named_by_its_path(
    owner: flow.Human, sections: list[dict[str, Any]], path: str, reason: str
) -> None:
    refused = owner.patch(ADMIN_PATH, body(*sections))
    assert refused.status_code == 400, refused.text
    assert field(refused).get(path) == reason, field(refused)


def test_the_page_and_the_footer_have_their_limits(owner: flow.Human) -> None:
    twenty_one = [text("x")] * 21
    assert field(owner.patch(ADMIN_PATH, body(*twenty_one))) == {"pages.en.sections": "invalid"}
    assert field(owner.patch(ADMIN_PATH, {"pages": {"en": {"sections": []}}})) == {
        "pages.en.title": "required"
    }
    long_description = {"pages": {"en": {"title": "T", "description": "d" * 301, "sections": []}}}
    assert field(owner.patch(ADMIN_PATH, long_description)) == {"pages.en.description": "invalid"}
    assert field(owner.patch(ADMIN_PATH, {"pages": {"fr": page()}})) == {"pages.fr": "invalid"}
    assert field(owner.patch(ADMIN_PATH, {"default_language": "fr"})) == {
        "default_language": "invalid"
    }
    social = [{"label": "l", "href": "https://example.com"}] * 9
    assert field(owner.patch(ADMIN_PATH, {"footer": {"social": social}})) == {
        "footer.social": "invalid"
    }
    bad_link = {"footer": {"social": [{"label": "l", "href": "http://example.com"}]}}
    assert field(owner.patch(ADMIN_PATH, bad_link)) == {"footer.social.0.href": "invalid"}
    assert field(owner.patch(ADMIN_PATH, {"colour": "red"})) == {"colour": "extra_forbidden"}


def test_enabled_needs_a_page_in_the_default_language(owner: flow.Human) -> None:
    assert field(owner.patch(ADMIN_PATH, {"enabled": True})) == {"pages.en": "required"}
    german = {"enabled": True, "default_language": "de", "pages": {"en": page(text("x"))}}
    assert field(owner.patch(ADMIN_PATH, german)) == {"pages.de": "required"}
    german["pages"] = {"de": page(text("x"))}
    assert owner.patch(ADMIN_PATH, german).status_code == 200


def test_only_the_instance_admin_edits_it(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    other = flow.human(make_client, migrated, "someone")
    assert other.get(ADMIN_PATH).status_code == 403
    assert other.patch(ADMIN_PATH, {"enabled": False}).status_code == 403


def test_the_join_host_never_serves_it(owner: flow.Human, make_client: ClientFactory) -> None:
    owner.patch(ADMIN_PATH, body(text(GOOD), enabled=True))
    answer = join_client(make_client).get("/api/v1/landing", follow_redirects=False)
    assert answer.status_code in (302, 404)
    assert "markdown" not in answer.text


def _race(migrated: Engine, owner: flow.Human, language: str, footer: dict[str, Any]) -> None:
    """The first edit holds the lock while the second, on its own connection, waits."""
    first, second = migrated.connect(), migrated.connect()
    started, saved = threading.Event(), threading.Event()

    def edit() -> None:
        with second.begin():
            started.set()
            landing.lock(second)
            landing.save(
                second, landing.check({"footer": footer}, landing.stored(second)), owner.id
            )
            saved.set()

    pool = ThreadPoolExecutor(max_workers=1)
    first_tx = first.begin()
    try:
        landing.lock(first)
        edit_one = landing.check({"default_language": language}, landing.stored(first))
        landing.save(first, edit_one, owner.id)
        waiting = pool.submit(edit)
        assert started.wait(timeout=10)
        assert not saved.wait(timeout=0.5)  # held by the first edit
        first_tx.commit()
        waiting.result(timeout=10)
    finally:
        if first_tx.is_active:
            first_tx.rollback()
        first.close()
        pool.shutdown(wait=True, cancel_futures=True)
        second.close()


def test_two_edits_at_once_keep_both_fields(owner: flow.Human, migrated: Engine) -> None:
    """Two admins edit different fields at the same moment: the second waits for the
    first's row lock, reads what it wrote and keeps it, both when the row is first made
    and once it exists. SQLite serialises every writer anyway, so this runs on PostgreSQL
    and MariaDB. The first transaction is released on every exit before the worker is
    joined, so a failing assertion cannot leave CI waiting on a blocked thread."""
    if migrated.dialect.name == "sqlite":
        pytest.skip("SQLite serialises writers; the row lock is for the server databases")
    with migrated.begin() as conn:
        conn.execute(delete(t.instance_landing))
    for language, operator in (("de", "First"), ("en", "Second")):
        footer = {"operator": operator, "social": []}
        _race(migrated, owner, language, footer)
        got = owner.get(ADMIN_PATH).json()
        assert (got["default_language"], got["footer"]) == (language, footer)


@pytest.mark.parametrize(
    "section",
    [
        {"type": "steps", "items": [{"title": "a", "text": "b"}]},
        {"type": "scales", "items": [{"tag": "t", "title": "a", "text": "b"}]},
        {"type": "faq", "items": [{"q": "q", "a": "a"}]},
        {"type": "profiles", "handles": []},
        {"type": "explore", "projects": []},
    ],
)
def test_the_title_of_a_section_is_required_except_for_text_and_activity(
    owner: flow.Human, section: dict[str, Any]
) -> None:
    """§16.7: only `text` has an optional title; these five need one (a section of the page
    that is shown names itself)."""
    refused = owner.patch(ADMIN_PATH, body({"enabled": True, **section}))
    assert refused.status_code == 400, refused.text
    assert field(refused)["pages.en.sections.0.title"] == "required"
    titled = owner.patch(ADMIN_PATH, body({"enabled": True, "title": "A title", **section}))
    assert titled.status_code == 200, titled.text
