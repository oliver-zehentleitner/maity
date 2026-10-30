"""The instance's landing page (docs/api.md §16.7): what a visitor who is not signed in
sees at the instance's root, written by the instance admin and kept in the database.

The page is per language `{title, description, sections}`; each section has a type and the
fields of that type, checked here with the path of the first field that breaks a rule
(`pages.de.sections.2.items.0.title`). The Markdown is checked against exactly what the
hub renders: text, headings, emphasis, lists, quotes, fenced code and links whose target is
an `https` URL or a path of this host (`/login`). No image and no raw HTML outside fenced
code; the first line that breaks a rule is named in the refusal.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import Connection, insert, select, update
from sqlalchemy.exc import IntegrityError

from maity_hub import clock
from maity_hub import tables as t
from maity_hub.errors import invalid
from maity_hub.views import ts

ROW = "landing"  # the one row of `instance_landing`
LANGUAGES = ("en", "de")  # the languages of §6.2
SECTION_MAX = 20
STORED_MAX = 256 * 1024  # bytes of UTF-8 (§16.7)
FIELDS = ("enabled", "default_language", "pages", "footer")
STATS = ("people", "agents", "public_projects", "cards_done_week", "people_online", "agents_online")
DEMO_KINDS = ("cmd", "out", "note")  # the lines of the demo's terminal (§16.7)
HANDLE = re.compile(r"[a-z0-9][a-z0-9-]{1,62}")
FULL_NAME = re.compile(r"[a-z0-9][a-z0-9-]{1,30}/[a-z0-9][a-z0-9-]{1,62}")
# C0 control characters other than tab, newline and carriage return (§16.7): no page has
# them, and without them JSON escapes a page to at most three times its size.
CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")

# A fence as `web/js/markdown.js` reads one: three or more backticks or tildes, up to
# three spaces in; a backtick fence's info string holds no backtick. It closes on the
# same character, at least as many, and nothing but whitespace after.
FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
# An HTML tag, a comment or a declaration: `<a`, `</p>`, `<!--`, `<!DOCTYPE`, `<br/>`.
TAG = re.compile(r"<(?:[A-Za-z][A-Za-z0-9-]*(?:\s|/?>|$)|/[A-Za-z]|!)")
IMAGE = re.compile(r"!\[")
# `[text](target …)`: what the dashboard turns into a link; the target is checked.
LINK = re.compile(r"\[[^\[\]\n]*\]\(\s*([^)\s]*)")
# A bare `https://…`, which the dashboard links as well (`web/js/markdown.js`).
BARE = re.compile(r"https://[^\s<>()]+")
HOST_LABEL = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?")


def safe_target(value: str) -> bool:
    """An `https` URL with a host and no credentials, or a dashboard path of §16.11: one `/`,
    no `//` and no fragment."""
    if any(c.isspace() or ord(c) < 32 or c == "\\" for c in value):
        return False
    if value.startswith("/"):
        return not value.startswith("//") and "#" not in value
    if not value.startswith("https://"):  # no http, javascript:, data:, //, lookalikes
        return False
    try:
        parts = urlsplit(value)
        port = parts.port  # a port that is no number, or out of range, raises
        host = parts.hostname
    except ValueError:
        return False
    if parts.scheme != "https" or "@" in parts.netloc or not host:
        return False
    if port is not None and not 1 <= port <= 65535:
        return False
    labels = host.split(".")
    return len(labels) >= 2 and all(HOST_LABEL.fullmatch(label) for label in labels)


def markdown_problem(text: str) -> str | None:
    """`line N` of the first line that breaks the rules, or None when the text is fine."""
    close: re.Pattern[str] | None = None
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    for number, line in enumerate(lines, start=1):
        if close is not None:
            if close.match(line):
                close = None
            continue  # inside fenced code everything is text, to the end if never closed
        opened = FENCE.match(line)
        if opened and not (opened.group(1)[0] == "`" and "`" in opened.group(2)):
            mark = re.escape(opened.group(1)[0])
            close = re.compile(rf"^ {{0,3}}{mark}{{{len(opened.group(1))},}}\s*$")
            continue
        if TAG.search(line) or IMAGE.search(line):
            return f"line {number}"
        if any(not safe_target(target) for target in LINK.findall(line)):
            return f"line {number}"
        if any(not safe_target(bare.rstrip(".,;:!?'\"")) for bare in BARE.findall(line)):
            return f"line {number}"
    return None


def _text(value: object, maximum: int) -> str | None:
    if not isinstance(value, str) or not 1 <= len(value) <= maximum:
        return None
    if any(ord(c) < 32 or ord(c) == 127 for c in value):
        return None
    return value


def _control(value: object) -> bool:
    return isinstance(value, str) and CONTROL.search(value) is not None


# --- the fields of a page ------------------------------------------------------------------
#
# A field is `(kind, …, required)`: ("text", maximum, required), ("md", bytes, required),
# ("link", required), ("int", low, high, required), ("object", {name: field}, required),
# ("list", item, low, high, required), ("choice", options, low, high, required),
# ("enum", options, required) and ("names", pattern, high, required). An absent optional field
# is left out of the stored page.

Spec = tuple[Any, ...]


def _link() -> Spec:
    return ("object", {"label": ("text", 40, True), "href": ("href", True)}, True)


def _points() -> Spec:
    return ("list", ("text", 120, True), 0, 5, False)


SECTIONS: dict[str, dict[str, Spec]] = {
    "hero": {
        "eyebrow": ("text", 40, False),
        "title": ("text", 120, True),
        "subline": ("text", 300, False),
        "cta_primary": _link(),
        "cta_secondary": (*_link()[:-1], False),
        "note": ("md", 500, False),
    },
    "stats": {"items": ("choice", STATS, 1, len(STATS), True)},
    "steps": {
        "title": ("text", 120, True),
        "items": (
            "list",
            (
                "object",
                {
                    "title": ("text", 80, True),
                    "text": ("text", 300, True),
                    "code": ("text", 300, False),
                },
                True,
            ),
            1,
            6,
            True,
        ),
    },
    "scales": {
        "title": ("text", 120, True),
        "items": (
            "list",
            (
                "object",
                {
                    "tag": ("text", 40, True),
                    "title": ("text", 80, True),
                    "text": ("text", 300, True),
                    "points": _points(),
                },
                True,
            ),
            1,
            4,
            True,
        ),
    },
    "faq": {
        "title": ("text", 120, True),
        "items": (
            "list",
            ("object", {"q": ("text", 200, True), "a": ("md", 2000, True)}, True),
            1,
            20,
            True,
        ),
    },
    "demo": {
        "title": ("text", 120, True),
        "subline": ("text", 300, False),
        "terminal_lines": (
            "list",
            (
                "object",
                {"kind": ("enum", DEMO_KINDS, True), "text": ("text", 200, True)},
                True,
            ),
            1,
            8,
            True,
        ),
        "inbox": (
            "object",
            {
                "from": ("text", 80, True),
                "question": ("text", 300, True),
                "context": ("text", 300, False),
            },
            False,
        ),
        "steps": (
            "list",
            ("object", {"title": ("text", 80, True), "text": ("text", 300, True)}, True),
            3,
            3,
            True,
        ),
    },
    "opensource": {
        "title": ("text", 120, True),
        "markdown": ("md", 600, False),
        "tiles": (
            "list",
            ("object", {"title": ("text", 80, True), "text": ("text", 300, True)}, True),
            1,
            3,
            True,
        ),
        "links": ("list", _link(), 0, 4, False),
    },
    "cta_band": {
        "title": ("text", 120, True),
        "text": ("text", 300, False),
        "cta": _link(),
    },
    "text": {"title": ("text", 120, False), "markdown": ("md", 16 * 1024, True)},
    "activity": {"title": ("text", 120, False), "count": ("int", 1, 20, True)},
    "profiles": {
        "title": ("text", 120, True),
        "markdown": ("md", 2000, False),
        "handles": ("names", HANDLE, 2, True),
    },
    "explore": {
        "title": ("text", 120, True),
        "projects": ("names", FULL_NAME, 3, True),
    },
    "collab": {
        "title": ("text", 120, False),
        "text": ("text", 300, False),
        "items": (
            "list",
            (
                "object",
                {
                    "tag": ("text", 40, True),
                    "title": ("text", 80, True),
                    "points": _points(),
                    "cta": _link(),
                },
                True,
            ),
            2,
            2,
            True,
        ),
        "footnote": ("text", 300, False),
    },
}


class Problems:
    """The first reason found for each field path, in the order the fields are read."""

    def __init__(self) -> None:
        self.fields: dict[str, str] = {}

    def add(self, path: str, reason: str) -> None:
        self.fields.setdefault(path, reason)

    def __bool__(self) -> bool:
        return bool(self.fields)


def _field(value: Any, spec: Spec, path: str, found: Problems) -> Any:
    """The value as it is stored, or None after a problem was recorded for `path`."""
    kind = spec[0]
    if _control_in(value):
        found.add(path, "control_character")
        return None
    if kind == "text":
        text = _text(value, spec[1])
        if text is None:
            found.add(path, "invalid")
        return text
    if kind == "md":
        if not isinstance(value, str) or not value.strip() or len(value.encode()) > spec[1]:
            found.add(path, "invalid")
            return None
        problem = markdown_problem(value)
        if problem is not None:
            found.add(path, problem)
            return None
        return value
    if kind == "href":
        if not isinstance(value, str) or not safe_target(value):
            found.add(path, "invalid")
            return None
        return value
    if kind == "int":
        if isinstance(value, bool) or not isinstance(value, int) or not spec[1] <= value <= spec[2]:
            found.add(path, "invalid")
            return None
        return value
    if kind == "object":
        return _object(value, spec[1], path, found)
    if kind == "list":
        return _list(value, spec, path, found)
    if kind == "enum":
        if not isinstance(value, str) or value not in spec[1]:
            found.add(path, "invalid")
            return None
        return value
    if kind == "choice":
        picked = value if isinstance(value, list) else None
        if (
            picked is None
            or not spec[2] <= len(picked) <= spec[3]
            or len(set(map(str, picked))) != len(picked)
            or any(item not in spec[1] for item in picked)
        ):
            found.add(path, "invalid")
            return None
        return list(picked)
    names = value if isinstance(value, list) else None  # "names"
    if (
        names is None
        or len(names) > spec[2]
        or len(set(map(str, names))) != len(names)
        or any(not isinstance(n, str) or not spec[1].fullmatch(n) for n in names)
    ):
        found.add(path, "invalid")
        return None
    return list(names)


def _control_in(value: Any) -> bool:
    return isinstance(value, str) and CONTROL.search(value) is not None


def _object(
    value: Any, fields: dict[str, Spec], path: str, found: Problems
) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        found.add(path, "invalid")
        return None
    out: dict[str, Any] = {}
    for name in value:
        if name not in fields:
            found.add(f"{path}.{name}", "extra_forbidden")
    for name, spec in fields.items():
        here = f"{path}.{name}"
        if name not in value or value[name] is None:
            if spec[-1]:
                found.add(here, "required")
            continue
        stored = _field(value[name], spec, here, found)
        if stored is not None:
            out[name] = stored
    return out if all(not p.startswith(path + ".") for p in found.fields) else None


def _list(value: Any, spec: Spec, path: str, found: Problems) -> list[Any] | None:
    if not isinstance(value, list) or not spec[2] <= len(value) <= spec[3]:
        found.add(path, "invalid")
        return None
    out = []
    for index, item in enumerate(value):
        stored = _field(item, spec[1], f"{path}.{index}", found)
        if stored is not None:
            out.append(stored)
    return out


def _section(value: Any, path: str, found: Problems) -> dict[str, Any] | None:
    if not isinstance(value, dict) or value.get("type") not in SECTIONS:
        found.add(f"{path}.type", "invalid")
        return None
    if "enabled" not in value:
        found.add(f"{path}.enabled", "required")
    elif not isinstance(value["enabled"], bool):
        found.add(f"{path}.enabled", "invalid")
    body = {k: v for k, v in value.items() if k not in ("type", "enabled")}
    checked = _object(body, SECTIONS[value["type"]], path, found)
    if checked is None or not isinstance(value.get("enabled"), bool):
        return None
    return {"type": value["type"], "enabled": value["enabled"], **checked}


def _page(value: Any, path: str, found: Problems) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        found.add(path, "invalid")
        return None
    for name in value:
        if name not in ("title", "description", "sections"):
            found.add(f"{path}.{name}", "extra_forbidden")
    title = None
    if value.get("title") is None:
        found.add(f"{path}.title", "required")
    else:
        title = _field(value["title"], ("text", 120, True), f"{path}.title", found)
    description = ""
    if value.get("description") is not None:
        if _control_in(value["description"]):
            found.add(f"{path}.description", "control_character")
        elif not isinstance(value["description"], str) or len(value["description"]) > 300:
            found.add(f"{path}.description", "invalid")
        else:
            description = value["description"]
    sections: list[dict[str, Any]] = []
    raw = value.get("sections", [])
    if not isinstance(raw, list) or len(raw) > SECTION_MAX:
        found.add(f"{path}.sections", "invalid")
    else:
        for index, one in enumerate(raw):
            checked = _section(one, f"{path}.sections.{index}", found)
            if checked is not None:
                sections.append(checked)
    if title is None:
        return None
    return {"title": title, "description": description, "sections": sections}


def _footer(value: Any, found: Problems) -> dict[str, Any] | None:
    spec: dict[str, Spec] = {
        "operator": ("text", 120, False),
        "social": (
            "list",
            ("object", {"label": ("text", 40, True), "href": ("href", True)}, True),
            0,
            8,
            False,
        ),
    }
    checked = _object(value, spec, "footer", found)
    if checked is None:
        return None
    return {"operator": checked.get("operator"), "social": checked.get("social", [])}


def check(body: object, current: dict[str, Any]) -> dict[str, Any]:
    """The setting after the instance admin's `PATCH` body: a field named replaces the stored
    one as a whole, a field left out stays. `invalid` names each field by its path."""
    if not isinstance(body, dict):
        raise invalid({"body": "not_an_object"})
    found = Problems()
    after = dict(current)
    for name, value in body.items():
        if name not in FIELDS:
            found.add(name, "extra_forbidden")
        elif name == "enabled":
            if isinstance(value, bool):
                after[name] = value
            else:
                found.add(name, "invalid")
        elif name == "default_language":
            if value in LANGUAGES:
                after[name] = value
            else:
                found.add(name, "invalid")
        elif name == "pages":
            if not isinstance(value, dict):
                found.add(name, "invalid")
                continue
            pages: dict[str, Any] = {}
            for tag, page in value.items():
                if tag not in LANGUAGES:
                    found.add(f"pages.{tag}", "invalid")
                    continue
                checked = _page(page, f"pages.{tag}", found)
                if checked is not None:
                    pages[tag] = checked
            after[name] = pages
        else:  # footer
            footer = (
                _footer(value, found) if value is not None else {"operator": None, "social": []}
            )
            if footer is not None:
                after[name] = footer
    if not found and after["enabled"] and after["default_language"] not in after["pages"]:
        found.add(f"pages.{after['default_language']}", "required")
    if (
        not found
        and len(json.dumps(after["pages"], ensure_ascii=False).encode())
        + len(json.dumps(after["footer"], ensure_ascii=False).encode())
        > STORED_MAX
    ):
        found.add("pages", "too_large")
    if found:
        raise invalid(found.fields)
    return after


def stored(conn: Connection) -> dict[str, Any]:
    """The setting as the admin last wrote it, or the defaults."""
    row = conn.execute(select(t.instance_landing).where(t.instance_landing.c.id == ROW)).first()
    if row is None:
        return {
            "enabled": False,
            "default_language": "en",
            "pages": {},
            "footer": {"operator": None, "social": []},
            "updated_at": None,
            "updated_by": None,
        }
    return {
        "enabled": bool(row.enabled),
        "default_language": row.default_language,
        "pages": row.pages or {},
        "footer": row.footer or {"operator": None, "social": []},
        "updated_at": ts(row.updated_at),
        "updated_by": row.updated_by,
    }


def lock(conn: Connection) -> None:
    """Take the setting's row for this transaction, made first if it is not there yet,
    before it is read: two edits at once run one after the other, so neither loses the
    other's fields and the first creation cannot race into a duplicate key. An edit
    that is refused rolls the made row back with it."""
    try:
        with conn.begin_nested():
            conn.execute(
                insert(t.instance_landing).values(
                    id=ROW,
                    enabled=False,
                    default_language="en",
                    pages={},
                    footer=None,
                    updated_at=clock.now(),
                    updated_by=None,
                )
            )
    except IntegrityError:
        pass  # it exists; lock it below
    conn.execute(
        select(t.instance_landing.c.id).where(t.instance_landing.c.id == ROW).with_for_update()
    )


def save(conn: Connection, value: dict[str, Any], by: str) -> None:
    """Write the edit into the locked row (`lock` first)."""
    conn.execute(
        update(t.instance_landing)
        .where(t.instance_landing.c.id == ROW)
        .values(
            enabled=value["enabled"],
            default_language=value["default_language"],
            pages=value["pages"],
            footer=value["footer"],
            updated_at=clock.now(),
            updated_by=by,
        )
    )


def public(value: dict[str, Any]) -> dict[str, Any]:
    """`GET /landing`: the same body for every visitor, never who wrote it."""
    if not value["enabled"]:
        return {"enabled": False}
    return {key: value[key] for key in (*FIELDS, "updated_at")}


def etag(body: dict[str, Any]) -> str:
    raw = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    return '"' + hashlib.sha256(raw).hexdigest()[:32] + '"'
