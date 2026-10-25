"""The instance's landing page (docs/api.md §16.7): what a visitor who is not signed in
sees at the dashboard's root, written by the instance admin and kept in the database.

The Markdown is checked against exactly what the dashboard renders: text, headings,
emphasis, lists, quotes, fenced code and links whose target is an `https` URL or a
dashboard route (`/#/…`). No image and no raw HTML outside fenced code; the first line
that breaks a rule is named in the refusal.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import Connection, delete, insert, select

from maity_hub import clock
from maity_hub import tables as t
from maity_hub.errors import invalid
from maity_hub.views import ts

ROW = "landing"  # the one row of `instance_landing`
MAX_TITLE, MAX_LABEL = 120, 40
MAX_MARKDOWN = 64 * 1024
FIELDS = ("enabled", "title", "markdown", "cta")

FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
# An HTML tag, a comment or a declaration: `<a`, `</p>`, `<!--`, `<!DOCTYPE`, `<br/>`.
TAG = re.compile(r"<(?:[A-Za-z][A-Za-z0-9-]*(?:\s|/?>|$)|/[A-Za-z]|!)")
IMAGE = re.compile(r"!\[")
# `[text](target …)`: what the dashboard turns into a link; the target is checked.
LINK = re.compile(r"\[[^\[\]\n]*\]\(\s*([^)\s]*)")
# A bare `https://…`, which the dashboard links as well (`web/js/markdown.js`).
BARE = re.compile(r"https://[^\s<>()]+")
HOST_LABEL = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?")


def safe_target(value: str) -> bool:
    """An `https` URL with a host and no credentials, or a dashboard route `/#/…`."""
    if any(c.isspace() or ord(c) < 32 or c == "\\" for c in value):
        return False
    if value.startswith("/#/"):
        return True
    if not value.startswith("https://"):  # no http, javascript:, data:, //, lookalikes
        return False
    parts = urlsplit(value)
    if parts.scheme != "https" or "@" in parts.netloc or not parts.hostname:
        return False
    host = parts.hostname
    labels = host.split(".")
    return len(labels) >= 2 and all(HOST_LABEL.fullmatch(label) for label in labels)


def markdown_problem(text: str) -> str | None:
    """`line N` of the first line that breaks the rules, or None when the text is fine."""
    fence: str | None = None
    for number, line in enumerate(text.splitlines(), start=1):
        opened = FENCE.match(line)
        if fence is not None:
            if opened and opened.group(1)[0] == fence[0] and len(opened.group(1)) >= len(fence):
                fence = None
            continue  # inside fenced code everything is text
        if opened:
            fence = opened.group(1)
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


def check(body: object, current: dict[str, Any]) -> dict[str, Any]:
    """The setting after the instance admin's `PATCH` body; `invalid` names each field."""
    if not isinstance(body, dict):
        raise invalid({"body": "not_an_object"})
    errors: dict[str, str] = {}
    after = dict(current)
    for name, value in body.items():
        if name not in FIELDS:
            errors[name] = "extra_forbidden"
        elif name == "enabled":
            if isinstance(value, bool):
                after[name] = value
            else:
                errors[name] = "invalid"
        elif value is None:
            after[name] = None
        elif name == "title":
            found = _text(value, MAX_TITLE)
            if found is None:
                errors[name] = "invalid"
            else:
                after[name] = found
        elif name == "markdown":
            if not isinstance(value, str) or not value.strip() or len(value) > MAX_MARKDOWN:
                errors[name] = "invalid"
            else:
                problem = markdown_problem(value)
                if problem is None:
                    after[name] = value
                else:
                    errors[name] = problem
        else:  # cta
            label = _text(value.get("label"), MAX_LABEL) if isinstance(value, dict) else None
            href = value.get("href") if isinstance(value, dict) else None
            if not isinstance(value, dict) or set(value) != {"label", "href"} or label is None:
                errors[name] = "invalid"
            elif not isinstance(href, str) or not safe_target(href):
                errors["cta.href"] = "invalid"
            else:
                after[name] = {"label": label, "href": href}
    if not errors and after["enabled"] and not after["markdown"]:
        errors["markdown"] = "required"
    if errors:
        raise invalid(errors)
    return after


def stored(conn: Connection) -> dict[str, Any]:
    """The setting as the admin last wrote it, or the defaults."""
    row = conn.execute(select(t.instance_landing).where(t.instance_landing.c.id == ROW)).first()
    if row is None:
        return {"enabled": False, "title": None, "markdown": None, "cta": None,
                "updated_at": None, "updated_by": None}  # fmt: skip
    return {
        "enabled": bool(row.enabled),
        "title": row.title,
        "markdown": row.markdown,
        "cta": row.cta,
        "updated_at": ts(row.updated_at),
        "updated_by": row.updated_by,
    }


def save(conn: Connection, value: dict[str, Any], by: str) -> None:
    conn.execute(delete(t.instance_landing).where(t.instance_landing.c.id == ROW))
    conn.execute(
        insert(t.instance_landing).values(
            id=ROW,
            enabled=value["enabled"],
            title=value["title"],
            markdown=value["markdown"],
            cta=value["cta"],
            updated_at=clock.now(),
            updated_by=by,
        )
    )


def public(value: dict[str, Any]) -> dict[str, Any]:
    """`GET /landing`: the same body for every visitor, never who wrote it."""
    if not value["enabled"]:
        return {"enabled": False}
    return {key: value[key] for key in ("enabled", "title", "markdown", "cta", "updated_at")}


def etag(body: dict[str, Any]) -> str:
    raw = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    return '"' + hashlib.sha256(raw).hexdigest()[:32] + '"'
