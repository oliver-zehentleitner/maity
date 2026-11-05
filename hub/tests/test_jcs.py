"""RFC 8785 canonical form for a value the owner's consent stores (docs/api.md §6.2)."""

from __future__ import annotations

import hashlib
import json

import pytest

from maity_hub.jcs import MAX_INTEGER, MIN_INTEGER, CanonicalError, canonicalize, check_tokens

WORKED = {"note": 'Grüße / "ok"', "n": 1}
WORKED_CANONICAL = '{"n":1,"note":"Grüße / \\"ok\\""}'
WORKED_SHA256 = "1846cbe396dd58d13909a4f8fa91496421d2d7a1441f0c4e783251a18726f8e3"


def test_the_worked_value_matches_the_contract() -> None:
    text = canonicalize(WORKED)
    assert text == WORKED_CANONICAL
    assert hashlib.sha256(text.encode("utf-8")).hexdigest() == WORKED_SHA256


def test_strings_escape_only_what_the_rfc_escapes() -> None:
    assert canonicalize('é/"\n\u0001') == '"é/\\"\\n\\u0001"'
    assert canonicalize({"b": 1, "a": 2}) == '{"a":2,"b":1}'
    assert canonicalize([True, False, None]) == "[true,false,null]"


def test_object_keys_sort_by_utf16_code_units() -> None:
    """U+1F600 is one code point above U+FFFD and two UTF-16 units starting at U+D83D,
    which sorts first."""
    emoji = "\U0001f600"
    replacement = "\ufffd"
    text = canonicalize({emoji: 1, replacement: 2})
    assert text.index(emoji) < text.index(replacement)


def test_a_fraction_or_an_exponent_or_a_bool_is_not_an_integer() -> None:
    for token in ("1.0", "1e2", "1.5", "-2e1"):
        with pytest.raises(CanonicalError) as caught:
            check_tokens(json.loads(token))
        assert caught.value.code == "not_an_integer"
    with pytest.raises(CanonicalError) as caught:
        check_tokens({"grace_minutes": True})
    assert caught.value.code == "not_an_integer"
    check_tokens(True, bool_ok=True)
    for token in ("1", "0", "1.0"):
        with pytest.raises(CanonicalError) as caught:
            check_tokens(json.loads(token), bool_ok=True)
        assert caught.value.code == "not_an_integer"


def test_an_integer_outside_the_recommended_range_is_not_an_integer() -> None:
    for value in (MAX_INTEGER + 1, MIN_INTEGER - 1):
        with pytest.raises(CanonicalError) as caught:
            canonicalize(value)
        assert caught.value.code == "not_an_integer"
    assert canonicalize(MAX_INTEGER) == str(MAX_INTEGER)
    assert canonicalize(MIN_INTEGER) == str(MIN_INTEGER)


def test_a_lone_surrogate_is_rejected_in_a_string_and_in_a_key() -> None:
    with pytest.raises(CanonicalError) as caught:
        canonicalize("\udead")
    assert caught.value.code == "lone_surrogate"
    with pytest.raises(CanonicalError) as caught:
        canonicalize({"\udead": 1})
    assert caught.value.code == "lone_surrogate"
