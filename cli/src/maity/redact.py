"""Credentials out of what maity prints (§13: no command prints a credential).

A Git remote may carry a token in its URL (`https://x-access-token:<token>@github.com/…`), and
git and gh repeat that URL in their own errors. Whatever names a remote, an upstream or a line of
their output goes through `without_userinfo` before it reaches a message, an error, a log line or
the hub.
"""

from __future__ import annotations

import re

# `scheme://userinfo@`: everything between `//` and the first `@` of the authority.
_USERINFO = re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://)[^/?#\s@]*@")


def without_userinfo(text: str) -> str:
    """`text` with the userinfo (`user:password@`) taken out of every URL in it."""
    return _USERINFO.sub(r"\1", text)
