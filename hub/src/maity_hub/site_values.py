"""The instance's site values (docs/api.md §16.7.3): name and value pairs the instance admin
keeps for the placeholders of a site file. The dashboard puts them in when it imports the
file, so the hub stores only finished text. The values are shown publicly once imported; a
secret has no place here. `refuse_placeholders` keeps an unfilled `{{name}}` off every public
text, whichever way it was written.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from sqlalchemy import Connection

from maity_hub import instance_settings as store
from maity_hub.errors import invalid

SETTING = "site_values.values"
NAME = re.compile(r"[a-z][a-z0-9_]{0,39}")
MAX_VALUES = 50
MAX_VALUE = 500
# Written as a placeholder, a slip included (`{{ Name }}`). `{{ .Values.x }}` and `{{#if}}`, as
# a page about a template language may quote them, are not placeholders.
PLACEHOLDER = re.compile(r"\{\{\s*[A-Za-z][A-Za-z0-9_-]*\s*\}\}")


def _value_ok(value: object) -> bool:
    return (
        isinstance(value, str)
        and 1 <= len(value) <= MAX_VALUE
        and value.strip() == value
        and not any(ord(c) < 32 or ord(c) == 127 for c in value)
    )


def problems(values: object) -> dict[str, str]:
    """The refused fields of a `values` object, by path; empty when it can be stored."""
    if not isinstance(values, dict) or len(values) > MAX_VALUES:
        return {"values": "invalid"}
    found: dict[str, str] = {}
    for name, value in values.items():
        if NAME.fullmatch(name) is None or not _value_ok(value):
            found[f"values.{name}"] = "invalid"
        elif "{{" in value:
            found[f"values.{name}"] = "unresolved_placeholder"
    return found


def _check(value: object) -> object | None:
    return None if problems(value) else value


store.register(store.Setting(SETTING, _check, {}))


def view(conn: Connection) -> dict[str, Any]:
    return {"values": store.stored(conn, "site_values").get(SETTING, {})}


def patch(conn: Connection, body: object, by: str) -> None:
    """`values` replaces the stored pairs as a whole: a name left out is gone."""
    if not isinstance(body, dict):
        raise invalid({"body": "not_an_object"})
    extra = {name: "extra_forbidden" for name in body if name != "values"}
    if extra or "values" not in body:
        raise invalid(extra or {"values": "required"})
    found = problems(body["values"])
    if found:
        raise invalid(found)
    store.put(conn, SETTING, body["values"] or None, by)


def refuse_placeholders(value: Any, path: str, add: Callable[[str, str], object]) -> None:
    """Every string under `value` still holding a placeholder, by its path."""
    if isinstance(value, str):
        if PLACEHOLDER.search(value):
            add(path, "unresolved_placeholder")
    elif isinstance(value, dict):
        for key, item in value.items():
            refuse_placeholders(item, f"{path}.{key}" if path else str(key), add)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            refuse_placeholders(item, f"{path}.{index}" if path else str(index), add)
