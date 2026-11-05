"""RFC 8785 (JSON Canonicalization Scheme) for one value the owner's consent stores.

The canonical form is one string. `null`, `true` and `false` are those tokens. A string is a
JSON string in raw UTF-8: only `"`, `\\` and the control characters U+0000 through U+001F are
escaped, and no other character is. A number is an integer in the range RFC 8785 recommends
(a SHOULD, from `-(2^53)+1` to `2^53-1`), written in base 10 with no fraction and no exponent.
A fraction, an exponent or an integer outside that range is `not_an_integer`. A lone surrogate
is `lone_surrogate`. An object's keys are sorted by UTF-16 code units. There is no whitespace.
"""

from __future__ import annotations

from typing import Any

# RFC 8785 Appendix B, note 1: the range it recommends for integers, which is Maity's input rule.
MIN_INTEGER = -(2**53) + 1
MAX_INTEGER = 2**53 - 1


class CanonicalError(Exception):
    """A value RFC 8785 will not canonicalise, or that Maity refuses before that."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _lone(text: str) -> bool:
    return any(0xD800 <= ord(char) <= 0xDFFF for char in text)


def has_lone_surrogate(value: Any) -> bool:
    """Whether `value` holds a lone surrogate in a string or an object key."""
    if isinstance(value, str):
        return _lone(value)
    if isinstance(value, list):
        return any(has_lone_surrogate(item) for item in value)
    if isinstance(value, dict):
        return any(
            has_lone_surrogate(key) or has_lone_surrogate(item) for key, item in value.items()
        )
    return False


def _string(text: str) -> str:
    if _lone(text):
        raise CanonicalError("lone_surrogate")
    parts = ['"']
    for char in text:
        code = ord(char)
        if char == '"':
            parts.append('\\"')
        elif char == "\\":
            parts.append("\\\\")
        elif char == "\b":
            parts.append("\\b")
        elif char == "\t":
            parts.append("\\t")
        elif char == "\n":
            parts.append("\\n")
        elif char == "\f":
            parts.append("\\f")
        elif char == "\r":
            parts.append("\\r")
        elif code < 0x20:
            parts.append(f"\\u{code:04x}")
        else:
            parts.append(char)
    parts.append('"')
    return "".join(parts)


def _integer(value: int) -> str:
    if value < MIN_INTEGER or value > MAX_INTEGER:
        raise CanonicalError("not_an_integer")
    return str(value)


def check_tokens(value: Any, *, bool_ok: bool = False) -> None:
    """The number and string tokens of a raw JSON value, before a model coerces them.

    A boolean is a boolean token only where the field itself is one (`bool_ok`). Nested, or
    where the field is stored as a number, `true` is not an integer. A float is a fraction
    or an exponent (`1.0`, `1e2`): `not_an_integer`, and so is an integer outside the range.
    """
    if value is None or isinstance(value, str):
        if isinstance(value, str) and _lone(value):
            raise CanonicalError("lone_surrogate")
        return
    if isinstance(value, bool):
        if not bool_ok:
            raise CanonicalError("not_an_integer")
        return
    if isinstance(value, float):
        raise CanonicalError("not_an_integer")
    if isinstance(value, int):
        # `1` and `0` are number tokens. A boolean field accepts `true` and `false` only.
        if bool_ok:
            raise CanonicalError("not_an_integer")
        _integer(value)
        return
    if isinstance(value, list):
        for item in value:
            check_tokens(item, bool_ok=False)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str) or _lone(key):
                raise CanonicalError("lone_surrogate")
            check_tokens(item, bool_ok=False)
        return
    raise CanonicalError("not_an_integer")


def canonicalize(value: Any) -> str:
    """The RFC 8785 canonical form of `value`, which is already a JSON value of the kinds
    Maity stores (no float: a float was rejected by `check_tokens`)."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return _integer(value)
    if isinstance(value, float):
        raise CanonicalError("not_an_integer")
    if isinstance(value, str):
        return _string(value)
    if isinstance(value, list):
        return "[" + ",".join(canonicalize(item) for item in value) + "]"
    if isinstance(value, dict):
        keys: list[str] = []
        for key in value:
            if not isinstance(key, str) or _lone(key):
                raise CanonicalError("lone_surrogate")
            keys.append(key)
        keys.sort(key=lambda key: key.encode("utf-16-be"))
        body = ",".join(f"{_string(key)}:{canonicalize(value[key])}" for key in keys)
        return "{" + body + "}"
    raise TypeError(f"cannot canonicalise {type(value).__name__}")
