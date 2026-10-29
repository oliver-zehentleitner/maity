"""docs/api.md §16.7: the instance's landing page."""

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
OFF = {"enabled": False, "title": None, "markdown": None, "cta": None}
GOOD = "# Bring your own agent\n\nRead [the docs](https://example.com/docs) or [sign in](/login)."


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
    assert got == {
        "enabled": False, "title": None, "markdown": None, "cta": None,
        "updated_at": None, "updated_by": None,
    }  # fmt: skip


def test_the_admin_publishes_it_and_the_etag_follows(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    visitor = make_client()
    off_tag = public(visitor).headers["etag"]
    saved = owner.patch(
        ADMIN_PATH,
        {
            "enabled": True,
            "title": "Bring your own coding agent.",
            "markdown": GOOD,
            "cta": {"label": "Sign in", "href": "/login"},
        },
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["updated_by"] == owner.id and saved.json()["updated_at"]
    page = public(visitor)
    body = page.json()
    assert body == {
        "enabled": True,
        "title": "Bring your own coding agent.",
        "markdown": GOOD,
        "cta": {"label": "Sign in", "href": "/login"},
        "updated_at": saved.json()["updated_at"],
    }
    tag = page.headers["etag"]
    assert tag != off_tag
    assert public(visitor, **{"If-None-Match": tag}).status_code == 304
    assert public(visitor, **{"If-None-Match": off_tag}).status_code == 200
    owner.patch(ADMIN_PATH, {"enabled": False})
    disabled = public(visitor, **{"If-None-Match": tag})
    assert (disabled.status_code, disabled.json()) == (200, {"enabled": False})


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
    refused = owner.patch(ADMIN_PATH, {"markdown": markdown})
    assert refused.status_code == 400, markdown
    assert field(refused)["markdown"].startswith("line ")


def test_html_in_fenced_code_is_text(owner: flow.Human) -> None:
    text = "Install:\n\n```html\n<script>not run</script>\n```\n\nThen [sign in](/login)."
    assert owner.patch(ADMIN_PATH, {"markdown": text}).status_code == 200
    second = owner.patch(ADMIN_PATH, {"markdown": "one\n\nline three <b>"})
    assert field(second) == {"markdown": "line 3"}


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
    saved = owner.patch(ADMIN_PATH, {"markdown": markdown})
    assert saved.status_code == 200, (markdown, saved.text)


def test_a_page_at_the_markdown_limit_passes_the_body_cap(owner: flow.Human) -> None:
    """§16.7: 64 KiB of Markdown whose JSON escaping grows it on the wire is accepted;
    one byte more is the field's `invalid`, not 413; past 256 KiB the body is 413."""
    quoted = ('"' * 63 + "\n") * (landing.MAX_MARKDOWN // 64)  # each character escaped
    # The widest escaping of a valid page: `\u00e9` for two bytes, three times on the wire.
    widest = json.dumps({"markdown": "\u00e9" * (landing.MAX_MARKDOWN // 2)}, ensure_ascii=True)
    assert len(widest) > 3 * landing.MAX_MARKDOWN
    sent = owner.client.patch(
        f"/api/v1{ADMIN_PATH}",
        content=widest,
        headers={"X-CSRF-Token": owner.csrf, "Content-Type": "application/json"},
    )
    assert sent.status_code == 200, sent.text
    assert len(quoted.encode()) == landing.MAX_MARKDOWN
    saved = owner.patch(ADMIN_PATH, {"markdown": quoted})
    assert saved.status_code == 200, saved.text
    assert field(owner.patch(ADMIN_PATH, {"markdown": quoted + "x"})) == {"markdown": "invalid"}
    huge = owner.patch(ADMIN_PATH, {"markdown": "x" * (257 * 1024)})
    assert (huge.status_code, huge.json()["error"]["code"]) == (413, "payload_too_large")


@pytest.mark.parametrize(
    ("body", "fields"),
    [
        ({"markdown": "a\x01b"}, {"markdown": "control_character"}),
        ({"markdown": "a\x1b[31mred"}, {"markdown": "control_character"}),
        ({"title": "a\x00b"}, {"title": "control_character"}),
        ({"cta": {"label": "Go\x07", "href": "/login"}}, {"cta": "control_character"}),
        ({"cta": {"label": "Go", "href": "/login\x0b"}}, {"cta.href": "control_character"}),
    ],
)
def test_control_characters_are_refused(
    owner: flow.Human, body: dict[str, Any], fields: dict[str, str]
) -> None:
    assert field(owner.patch(ADMIN_PATH, body)) == fields


def test_tab_newline_and_carriage_return_are_text(owner: flow.Human) -> None:
    saved = owner.patch(ADMIN_PATH, {"markdown": "# Head\r\n\n\tindented\n"})
    assert saved.status_code == 200, saved.text


def test_the_larger_cap_is_the_landing_settings_alone(owner: flow.Human) -> None:
    refused = owner.patch("/me", {"display_name": "x" * (65 * 1024)})
    assert refused.status_code == 413


def test_the_markdown_is_capped_in_bytes() -> None:
    """64 KiB of UTF-8 (§16.7): a four-byte character counts four times."""
    fits = "\U0001f984" * (landing.MAX_MARKDOWN // 4)
    assert landing.check({"markdown": fits}, OFF)["markdown"] == fits
    with pytest.raises(ApiError) as over:
        landing.check({"markdown": fits + "x"}, OFF)
    assert over.value.details == {"fields": {"markdown": "invalid"}}


def test_the_other_fields_and_enabled_without_markdown(owner: flow.Human) -> None:
    assert field(owner.patch(ADMIN_PATH, {"enabled": True})) == {"markdown": "required"}
    assert field(owner.patch(ADMIN_PATH, {"title": ""})) == {"title": "invalid"}
    assert field(owner.patch(ADMIN_PATH, {"title": "x" * 121})) == {"title": "invalid"}
    assert field(owner.patch(ADMIN_PATH, {"cta": {"label": "Go", "href": "http://x.com"}})) == {
        "cta.href": "invalid"
    }
    assert field(owner.patch(ADMIN_PATH, {"cta": {"label": "x" * 41, "href": "/login"}})) == {
        "cta": "invalid"
    }
    for href in ("https://[example.com", "https://example.com:bad/", "https://example.com:0/"):
        cta = {"label": "Go", "href": href}
        assert field(owner.patch(ADMIN_PATH, {"cta": cta})) == {"cta.href": "invalid"}, href
    assert field(owner.patch(ADMIN_PATH, {"colour": "red"})) == {"colour": "extra_forbidden"}
    assert (
        owner.patch(
            ADMIN_PATH, {"cta": {"label": "Docs", "href": "https://example.com/docs"}}
        ).status_code
        == 200
    )


def test_only_the_instance_admin_edits_it(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    other = flow.human(make_client, migrated, "someone")
    assert other.get(ADMIN_PATH).status_code == 403
    assert other.patch(ADMIN_PATH, {"enabled": False}).status_code == 403


def test_the_join_host_never_serves_it(owner: flow.Human, make_client: ClientFactory) -> None:
    owner.patch(ADMIN_PATH, {"enabled": True, "markdown": GOOD})
    answer = join_client(make_client).get("/api/v1/landing", follow_redirects=False)
    assert answer.status_code in (302, 404)
    assert "markdown" not in answer.text


def _race(migrated: Engine, owner: flow.Human, title: str, cta: dict[str, str]) -> None:
    """The first edit holds the lock while the second, on its own connection, waits."""
    first, second = migrated.connect(), migrated.connect()
    started, saved = threading.Event(), threading.Event()

    def edit() -> None:
        with second.begin():
            started.set()
            landing.lock(second)
            landing.save(second, landing.check({"cta": cta}, landing.stored(second)), owner.id)
            saved.set()

    pool = ThreadPoolExecutor(max_workers=1)
    first_tx = first.begin()
    try:
        landing.lock(first)
        landing.save(first, landing.check({"title": title}, landing.stored(first)), owner.id)
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
    for title, label in (("First", "Made"), ("Second", "Existing")):
        cta = {"label": label, "href": "/login"}
        _race(migrated, owner, title, cta)
        got = owner.get(ADMIN_PATH).json()
        assert (got["title"], got["cta"]) == (title, cta)
