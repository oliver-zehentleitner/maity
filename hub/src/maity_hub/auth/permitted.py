"""The permitted-call allowlists of the access gates, in one format and with one matcher: what
an isolated agent (§6.2), a second-factor or enrolment session (§2.8.2, §2.8.5) and a pending
account (§2.7.5) may still call.

An entry is a method and a path template below `/api/v1`, written as the router writes the
route: `("POST", "/auth/sessions/{public_id}/confirm")`. A `{name}` stands for one path
segment that is not empty (the router's own `[^/]+`); a `{name:path}` for the rest of the
path, empty or with slashes. Everything else is compared character for character, the
method too. `tests/test_permitted_calls.py` holds every entry to a route of the router.

Each gate hands over the path it has always read (the raw request path, or the decoded one);
the matcher only compares."""

from __future__ import annotations

import re
from collections.abc import Iterator

API = "/api/v1"

METHODS = frozenset({"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE"})
_PARAM = re.compile(r"\{([a-z_][a-z0-9_]*)(:path)?\}")


def _pattern(template: str) -> re.Pattern[str]:
    parts: list[str] = []
    at = 0
    for found in _PARAM.finditer(template):
        parts.append(re.escape(template[at : found.start()]))
        parts.append("(?s:.*)" if found.group(2) else "[^/]+")
        at = found.end()
    parts.append(re.escape(template[at:]))
    return re.compile("".join(parts))


class Calls:
    """One allowlist: `(method, template)` entries, read as the module says."""

    def __init__(self, *entries: tuple[str, str]) -> None:
        for method, template in entries:
            if method not in METHODS:
                raise ValueError(f"not a method: {method!r}")
            if not template.startswith("/") or template == API or template.startswith(API + "/"):
                raise ValueError(f"a template is the path below {API}: {template!r}")
            if set("{}") & set(_PARAM.sub("", template)):
                raise ValueError(f"a parameter is {{name}} or {{name:path}}: {template!r}")
        self.entries = tuple(entries)
        self._exact = frozenset(e for e in entries if _PARAM.search(e[1]) is None)
        self._patterns = tuple(
            (method, _pattern(template)) for method, template in entries if _PARAM.search(template)
        )

    def __iter__(self) -> Iterator[tuple[str, str]]:
        return iter(self.entries)

    def admits(self, method: str, path: str) -> bool:
        """Whether the call `method` on `path` (below `/api/v1`) is on the list."""
        if (method, path) in self._exact:
            return True
        return any(m == method and p.fullmatch(path) for m, p in self._patterns)

    def admits_api(self, method: str, path: str) -> bool:
        """`admits` for a whole path: one that does not start with `/api/v1` is on no list."""
        return path.startswith(API) and self.admits(method, path[len(API) :])
