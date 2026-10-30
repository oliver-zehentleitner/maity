"""Credentials out of what maity prints (§13: no command prints a credential).

A Git remote may carry a token in its URL (`https://x-access-token:<token>@github.com/…`), and
git and gh repeat that URL in their own errors. Whatever names a remote, an upstream or a line of
their output goes through `without_userinfo` before it reaches a message, an error, a log line or
the hub.
"""

from __future__ import annotations

import re

# `scheme://userinfo@`: everything between `//` and the last `@` before the path or whitespace,
# so an `@` in a user or a password (`user:p@ss@host`) goes too. Anything else before that `@`
# is taken along, a `?`, `#`, quote, backtick or bracket included: an unencoded one may stand
# in a password, and better too much out than a rest of a password left in.
_USERINFO = re.compile(r"""(?i)\b([a-z][a-z0-9+.-]*://)[^/\s]*@""")


def without_userinfo(text: str) -> str:
    """`text` with the userinfo (`user:password@`) taken out of every URL in it."""
    return _USERINFO.sub(r"\1", text)
