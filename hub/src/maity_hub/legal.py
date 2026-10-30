"""The legal pages (docs/api.md §16.7.1): the operator's imprint, privacy notice and terms of
use, written by the instance admin and kept in the database, every version of them.

A `PATCH` replaces one page's languages as a whole and gives the page a new version, the hub's
time of the change; the earlier versions stay readable at their addresses, since a person may
have accepted one. A page is unset with `null`: it is not served, its versions stay.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy import Connection, func, insert, select, update
from sqlalchemy.exc import IntegrityError

from maity_hub import clock
from maity_hub import tables as t
from maity_hub.errors import invalid, rate_limited
from maity_hub.landing import CONTROL, LANGUAGES, Problems, markdown_problem
from maity_hub.views import ts

ROW = "legal"  # the one row of `instance_legal`
PAGES = ("imprint", "privacy", "terms")
ADDRESS = {"imprint": "impressum", "privacy": "privacy", "terms": "terms"}  # §16.11
MAX_TITLE = 120
MAX_MARKDOWN = 64 * 1024  # bytes of UTF-8 (§16.7.1)
MAX_LANGUAGES = 8
CHANGES_PER_DAY = 20


def _languages(value: Any, page: str, found: Problems) -> dict[str, dict[str, str]] | None:
    """The texts of one page per language, or None after a problem was recorded."""
    if not isinstance(value, dict) or not 1 <= len(value) <= MAX_LANGUAGES:
        found.add(page, "invalid")
        return None
    out: dict[str, dict[str, str]] = {}
    before = len(found.fields)
    for tag, text in value.items():
        here = f"{page}.{tag}"
        if tag not in LANGUAGES:
            found.add(here, "invalid")
            continue
        if not isinstance(text, dict):
            found.add(here, "invalid")
            continue
        for name in text:
            if name not in ("title", "markdown"):
                found.add(f"{here}.{name}", "extra_forbidden")
        title, markdown = text.get("title"), text.get("markdown")
        if title is None:
            found.add(f"{here}.title", "required")
        elif isinstance(title, str) and CONTROL.search(title):
            found.add(f"{here}.title", "control_character")
        elif not isinstance(title, str) or not 1 <= len(title) <= MAX_TITLE:
            found.add(f"{here}.title", "invalid")
        if markdown is None:
            found.add(f"{here}.markdown", "required")
        elif isinstance(markdown, str) and CONTROL.search(markdown):
            found.add(f"{here}.markdown", "control_character")
        elif (
            not isinstance(markdown, str)
            or not markdown.strip()
            or len(markdown.encode()) > MAX_MARKDOWN
        ):
            found.add(f"{here}.markdown", "invalid")
        else:
            problem = markdown_problem(markdown)
            if problem is not None:
                found.add(f"{here}.markdown", problem)
        if f"{here}.title" not in found.fields and f"{here}.markdown" not in found.fields:
            out[tag] = {"title": str(title), "markdown": str(markdown)}
    return out if len(found.fields) == before else None


class Change:
    """What a `PATCH` body asks for: a default language and/or one page (replaced or unset)."""

    def __init__(self) -> None:
        self.default_language: str | None = None
        self.page: str | None = None
        self.languages: dict[str, dict[str, str]] | None = None  # None with `page`: unset


def check(body: object) -> Change:
    if not isinstance(body, dict):
        raise invalid({"body": "not_an_object"})
    found = Problems()
    change = Change()
    for name, value in body.items():
        if name == "default_language":
            if value in LANGUAGES:
                change.default_language = value
            else:
                found.add(name, "invalid")
        elif name in PAGES:
            if change.page is not None:
                found.add(name, "one_page_per_call")
            elif value is None:
                change.page = name
            else:
                languages = _languages(value, name, found)
                if languages is not None:
                    change.page, change.languages = name, languages
        else:
            found.add(name, "extra_forbidden")
    if not body:
        found.add("body", "empty")
    if found:
        raise invalid(found.fields)
    return change


def lock(conn: Connection) -> None:
    """The setting's row for this transaction, made first when it is not there yet: two edits
    at once run one after the other, and the version a change gets is read after the lock."""
    try:
        with conn.begin_nested():
            conn.execute(
                insert(t.instance_legal).values(
                    id=ROW, default_language="en", updated_at=clock.now(), updated_by=None
                )
            )
    except IntegrityError:
        pass  # it exists; lock it below
    conn.execute(
        select(t.instance_legal.c.id).where(t.instance_legal.c.id == ROW).with_for_update()
    )


def _versions(conn: Connection, page: str) -> list[Any]:
    return list(
        conn.execute(
            select(t.legal_version)
            .where(t.legal_version.c.page == page)
            .order_by(t.legal_version.c.version.desc())
        ).all()
    )


def stored(conn: Connection) -> dict[str, Any]:
    """The setting as the admin last wrote it: the served texts and every earlier version."""
    row = conn.execute(select(t.instance_legal).where(t.instance_legal.c.id == ROW)).first()
    current = dict(conn.execute(select(t.legal_page.c.page, t.legal_page.c.current)).all())
    pages: dict[str, Any] = {}
    for page in PAGES:
        served = current.get(page)
        if served is None:
            pages[page] = None
            continue
        versions = _versions(conn, page)
        text = next(v for v in versions if v.version == served)
        pages[page] = {
            "version": served,
            "languages": text.languages,
            "versions": [v.version for v in versions if v.version != served],
        }
    return {
        "default_language": row.default_language if row is not None else "en",
        "pages": pages,
        "updated_at": ts(row.updated_at) if row is not None else None,
        "updated_by": row.updated_by if row is not None else None,
    }


def apply(conn: Connection, change: Change, by: str) -> None:
    """Write the change (`lock` first): a replaced page gets a new version, an unset page
    keeps its versions and is not served."""
    now = clock.now()
    if change.page is not None and change.languages is not None:
        recent = conn.execute(
            select(func.count()).where(
                t.legal_version.c.page == change.page,
                t.legal_version.c.created_at >= now - timedelta(hours=24),
            )
        ).scalar_one()
        if recent >= CHANGES_PER_DAY:
            raise rate_limited(24 * 3600)
        version = clock.rfc3339(now)
        taken = {v.version for v in _versions(conn, change.page)}
        while version in taken:  # two changes in one second: the later one is a second later
            now += timedelta(seconds=1)
            version = clock.rfc3339(now)
        conn.execute(
            insert(t.legal_version).values(
                page=change.page,
                version=version,
                languages=change.languages,
                created_at=now,
                created_by=by,
            )
        )
        _set_current(conn, change.page, version)
    elif change.page is not None:
        _set_current(conn, change.page, None)
    values: dict[str, Any] = {"updated_at": clock.now(), "updated_by": by}
    if change.default_language is not None:
        values["default_language"] = change.default_language
    conn.execute(update(t.instance_legal).where(t.instance_legal.c.id == ROW).values(**values))


def _set_current(conn: Connection, page: str, version: str | None) -> None:
    changed = conn.execute(
        update(t.legal_page).where(t.legal_page.c.page == page).values(current=version)
    ).rowcount
    if changed == 0:
        conn.execute(insert(t.legal_page).values(page=page, current=version))


def public(setting: dict[str, Any]) -> dict[str, Any]:
    """`GET /legal`: the pages that are set, without the text (§16.7.1)."""
    return {
        "default_language": setting["default_language"],
        "pages": {
            page: {"version": one["version"], "languages": sorted(one["languages"])}
            for page, one in setting["pages"].items()
            if one is not None
        },
    }
