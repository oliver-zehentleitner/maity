"""The hub's words (`catalog`, `words/<lang>.json`, §6.2): English complete, the rest true to it."""

from __future__ import annotations

import json
import re
import string
from pathlib import Path

import pytest

from maity_hub import catalog, languages
from maity_hub.auth import email_links

WORDS = Path(catalog.__file__).with_name("words")


def _file(tag: str) -> dict[str, str]:
    words: dict[str, str] = json.loads((WORDS / f"{tag}.json").read_text(encoding="utf-8"))
    return words


def _fields(text: str) -> set[str]:
    return {field for _, field, _, _ in string.Formatter().parse(text) if field}


def test_every_file_is_a_language_of_the_portal() -> None:
    assert {path.stem for path in WORDS.glob("*.json")} <= set(languages.INTERFACE)


@pytest.mark.parametrize("tag", languages.INTERFACE)
def test_a_translation_has_english_keys_and_placeholders(tag: str) -> None:
    path = WORDS / f"{tag}.json"
    if not path.exists():
        pytest.skip("no file yet")
    english = _file("en")
    for key, text in _file(tag).items():
        assert key in english, key
        assert re.fullmatch(r"[a-z_]+\.[a-z0-9_]+", key), key
        assert text.strip(), key
        assert _fields(text) == _fields(english[key]), key


def test_a_key_without_a_translation_reads_in_english() -> None:
    english, french = catalog.section("factor", "en"), catalog.section("factor", "fr")
    assert french == english
    assert catalog.section("frame", "fr")["sign_in"] != catalog.section("frame", "en")["sign_in"]


@pytest.mark.parametrize("tag", ["xx", "../en", None, 5])
def test_a_tag_outside_the_portal_reads_in_english(tag: object) -> None:
    assert catalog.section("frame", tag) == catalog.section("frame", "en")


def test_speaks_says_whether_a_section_has_its_own_words() -> None:
    assert catalog.speaks("frame", "ja")
    assert catalog.speaks("factor", "de")
    assert not catalog.speaks("frame", "xx")


@pytest.mark.parametrize(
    ("language", "opening", "line"),
    [
        ("en", "Hello Ada,", "Or enter this code in the browser where you asked for it: 123 456"),
        ("de", "Hallo Ada,", "Oder gib diesen Code in dem Browser ein"),
    ],
)
def test_the_sign_in_mail_reads_as_it_did(language: str, opening: str, line: str) -> None:
    body = email_links.mail_body(
        language=language,
        display_name="Ada",
        link="https://x/l",
        requested_at="now",
        browser=None,
        system="Linux",
        address="1.2.3.4",
        code="123456",
    )
    assert body.startswith(opening) and line in body and "https://x/l" in body


def test_values_with_braces_stay_as_they_are() -> None:
    body = email_links.mail_body(
        language="en",
        display_name="{evil}",
        link="https://x/l",
        requested_at="now",
        browser="b",
        system="s",
        address="a",
        code=None,
    )
    assert "Hello {evil}," in body
