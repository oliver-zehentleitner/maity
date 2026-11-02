"""The words the hub composes for a person: mails, link pages, bell titles, the public pages'
frame (§6.2, §18.4). One file per language, `words/<lang>.json`, of flat keys `<section>.<key>`;
a key without a translation reads in English. The API's own messages stay in English (§6.2).
"""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path

from maity_hub import languages

_DIRECTORY = Path(__file__).with_name("words")


@cache
def _file(language: str) -> dict[str, str]:
    path = _DIRECTORY / f"{language}.json"
    if not path.exists():
        return {}
    words: dict[str, str] = json.loads(path.read_text(encoding="utf-8"))
    return words


@cache
def _section(name: str, language: str) -> dict[str, str]:
    prefix = f"{name}."
    merged = {**_file("en"), **(_file(language) if language != "en" else {})}
    return {key[len(prefix) :]: text for key, text in merged.items() if key.startswith(prefix)}


def speaks(name: str, language: str) -> bool:
    """Whether a language has its own words for a section yet."""
    if language not in languages.INTERFACE:
        return False
    return any(key.startswith(f"{name}.") for key in _file(language))


def section(name: str, language: object) -> dict[str, str]:
    """A section's words in a language, English where it has none, and for a tag outside the
    portal's ten. Shared between callers: read it, do not change it."""
    tag = language if isinstance(language, str) and language in languages.INTERFACE else "en"
    return _section(name, tag)
