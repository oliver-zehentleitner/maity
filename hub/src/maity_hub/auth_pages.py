"""The pitch of `/login` and `/register` per language (docs/api.md §16.7.4): instance content the
instance admin writes as a whole, with no earlier versions. Only words: the forms stay the
dashboard's, and no sign-in depends on reading these.
"""

from __future__ import annotations

import unicodedata
from typing import Any

from sqlalchemy import Connection, select

from maity_hub import instance_settings as store
from maity_hub import render, site_values
from maity_hub import tables as t
from maity_hub.errors import invalid
from maity_hub.landing import CONTROL, LANGUAGES, Problems, markdown_problem
from maity_hub.views import ts

SETTING = "auth_pages.setting"
PAGES = ("sign_in", "sign_up")
KEYS = frozenset({"title", "subline", "point_1", "point_2", "point_3", "note"})
MAX_TEXT = 500
MAX_NOTE = 4 * 1024  # bytes of UTF-8
DEFAULT: dict[str, Any] = {"default_language": "en", "pages": {page: {} for page in PAGES}}


def _text(value: Any, path: str, found: Problems) -> str | None:
    """A text as it is stored: trimmed, on one line."""
    if not isinstance(value, str):
        found.add(path, "invalid")
        return None
    text = value.strip()
    if not 1 <= len(text) <= MAX_TEXT or any(
        unicodedata.category(c) in ("Cc", "Zl", "Zp") for c in text
    ):
        found.add(path, "invalid")
        return None
    return text


def _note(value: Any, path: str, found: Problems) -> str | None:
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value.encode()) > MAX_NOTE
        or CONTROL.search(value)
        or markdown_problem(value) is not None
    ):
        found.add(path, "invalid")
        return None
    return value


def _page(value: Any, path: str, found: Problems) -> dict[str, dict[str, str]]:
    if not isinstance(value, dict):
        found.add(path, "invalid")
        return {}
    languages: dict[str, dict[str, str]] = {}
    for language, texts in value.items():
        at = f"{path}.{language}"
        if language not in LANGUAGES or not isinstance(texts, dict):
            found.add(at, "invalid")
            continue
        kept: dict[str, str] = {}
        for key, text in texts.items():
            if key not in KEYS:
                found.add(f"{at}.{key}", "extra_forbidden")
                continue
            read = (_note if key == "note" else _text)(text, f"{at}.{key}", found)
            if read is not None:
                kept[key] = read
        languages[language] = kept
    return languages


def check(body: Any) -> dict[str, Any]:
    """The setting a `PATCH` or `check` body describes, or `invalid` with every refused path."""
    if not isinstance(body, dict):
        raise invalid({"body": "not_an_object"})
    found = Problems()
    for name in body:
        if name not in ("default_language", "pages"):
            found.add(str(name), "extra_forbidden")
    language = body.get("default_language", DEFAULT["default_language"])
    if not isinstance(language, str) or language not in LANGUAGES:
        found.add("default_language", "invalid")
    pages = body.get("pages", {})
    written: dict[str, dict[str, dict[str, str]]] = {page: {} for page in PAGES}
    if not isinstance(pages, dict):
        found.add("pages", "invalid")
    else:
        for page, value in pages.items():
            if page in PAGES:
                written[page] = _page(value, f"pages.{page}", found)
            else:
                found.add(f"pages.{page}", "extra_forbidden")
    site_values.refuse_placeholders(written, "pages", found.add)
    if found.fields:
        raise invalid(found.fields)
    return {"default_language": language, "pages": written}


def _stored_ok(value: object) -> object | None:
    return value if isinstance(value, dict) else None


store.register(store.Setting(SETTING, _stored_ok, DEFAULT))


def stored(conn: Connection) -> dict[str, Any]:
    return store.stored(conn, "auth_pages").get(SETTING, DEFAULT)  # type: ignore[no-any-return]


def view(conn: Connection) -> dict[str, Any]:
    """The setting as the admin reads it."""
    row = conn.execute(
        select(t.instance_setting.c.updated_at, t.instance_setting.c.updated_by).where(
            t.instance_setting.c.name == SETTING
        )
    ).first()
    return {
        **stored(conn),
        "updated_at": ts(row.updated_at) if row else None,
        "updated_by": row.updated_by if row else None,
    }


def save(conn: Connection, setting: dict[str, Any], by: str) -> None:
    store.put(conn, SETTING, setting, by)


def public(
    setting: dict[str, Any], page: str, lang: str | None, accept: str | None
) -> dict[str, Any]:
    """One page for a visitor: only the chosen language's keys, never another's (§16.7.4)."""
    languages = setting["pages"][page]
    offered = [language for language, texts in languages.items() if texts]
    language = render.best_language(offered, lang, accept) or setting["default_language"]
    return {"language": language, "texts": languages.get(language, {})}
