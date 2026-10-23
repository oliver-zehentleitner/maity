"""The one address syntax of docs/api.md §18.4: exactly one RFC 5321 `addr-spec`.

`local-part@domain`, ASCII only, at most 254 characters with a local part of at most
64, a domain of host-name labels with at least one dot (no IP literal). No display
name, no angle brackets, no comma, semicolon, whitespace or control character, and no
second `@` outside a quoted local part. The checked address is handed to SMTP as the
single recipient; nothing ever parses a list out of it.
"""

from __future__ import annotations

import re

MAX_ADDRESS = 254
MAX_LOCAL = 64

# RFC 5321 atext: letters, digits and these.
_ATOM = r"[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+"
# A quoted local part, without what §18.4 refuses anywhere: whitespace, comma,
# semicolon and angle brackets. A backslash quotes the next printable character.
_QCHAR = r"[!#-+\--:=?-\[\]-~]"
_QUOTED = rf'"(?:{_QCHAR}|\\[!-+\--:=?-~])*"'
_LOCAL = re.compile(rf"(?:{_ATOM}(?:\.{_ATOM})*|{_QUOTED})")
LABEL = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?")


def valid(value: object) -> bool:
    """Whether `value` is one address in the syntax of §18.4."""
    if not isinstance(value, str) or not value.isascii() or len(value) > MAX_ADDRESS:
        return False
    local, at, domain = value.rpartition("@")
    if not at or not local or len(local) > MAX_LOCAL:
        return False
    if _LOCAL.fullmatch(local) is None:
        return False
    labels = domain.split(".")
    return len(labels) >= 2 and all(LABEL.fullmatch(label) for label in labels)
