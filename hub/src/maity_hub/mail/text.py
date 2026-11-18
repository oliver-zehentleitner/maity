"""Text the hub did not write, as a mail carries it (docs/api.md §18.5).

A mail carries only the hub's own links. Whatever a human or an agent wrote (a name, a
note, a title, a reason) is quoted as plain text on one line, and anything a mail client
could turn into a link is defanged: `https[:]//`, `example[.]org`. A subject gets the same
treatment and a length limit, since it is shown before the mail is opened.

Every module that composes a mail (notification mail, invitations, registration, the
second-factor reset) uses these, so they live beside `headers`, not in one of those modules.
"""

from __future__ import annotations

import re

from maity_hub.mail import headers

SUBJECT_MAX = 120

_SCHEME_CHARS = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+.-")
_WORD = re.compile(r"\w")
_DOT = re.compile(r"(?<=[A-Za-z0-9-])\.(?=[A-Za-z])")


def _schemes(text: str) -> str:
    """`scheme://` as `scheme[:]//`: a letter at a word's start, then letters, digits, `+`,
    `.` or `-` up to the `:`. Each `://` looks back over its own run only, so the work grows
    with the text's length; the pattern it replaces tried every word start of a long run."""
    out = []
    last = 0
    at = text.find("://")
    while at >= 0:
        start = at
        while start > last and text[start - 1] in _SCHEME_CHARS:
            start -= 1
        # The leftmost letter at a word boundary: the run's first character after a
        # character that is no word character, or one after a `+`, `.` or `-`.
        boundary = (start == 0 or not _WORD.match(text[start - 1])) and start < at
        found = start < at and text[start].isascii() and text[start].isalpha() and boundary
        found = found or any(
            text[i - 1] in "+.-" and text[i].isascii() and text[i].isalpha()
            for i in range(start + 1, at)
        )
        if found:
            out.append(text[last:at])
            out.append("[:]")
            last = at + 1
        at = text.find("://", at + 1)
    out.append(text[last:])
    return "".join(out)


def defang(text: str) -> str:
    """No mail client turns this into a link: `https[:]//`, `example[.]org`,
    `www[.]x`, `me@example[.]org` (§18.5)."""
    return _DOT.sub("[.]", _schemes(text))


def quoted(text: str) -> str:
    """Text the hub did not write, as plain quoted text on one line."""
    return '"' + defang(" ".join(text.split())) + '"'


def subject_line(text: str) -> str:
    """A subject with text the hub did not write in it: on one line with every control
    character gone, defanged as the body is, and cut at `SUBJECT_MAX` (§18.5). A subject is
    shown before the mail is opened, so it is no place for a link either."""
    flat = defang(" ".join(headers.clean(text).split()))
    return flat if len(flat) <= SUBJECT_MAX else flat[: SUBJECT_MAX - 1] + "…"
