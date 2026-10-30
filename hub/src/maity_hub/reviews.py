"""The `review` of a `review_result` message (docs/api.md §8.4, "A review result cites what it
judged").

A review result names what it judged (`subject`), the exact commit (`head`), a verdict and the
places the reviewer read (`cites`). The hub checks the shape and stores it as given: it does not
read the repository. Every problem is reported at its own path, a cite's by its index
(`review.cites.2.line`), with one of `required`, `too_few`, `too_many`, `too_long` and `format`.
"""

from __future__ import annotations

import re
from typing import Any

SUBJECT_MAX = 120
PATH_MAX = 300
QUOTE_MAX = 300
CITES_MAX = 50
VERDICTS = ("approve", "changes", "comment")
HEAD = re.compile(r"[0-9a-f]{40}")
LINE_BREAK = re.compile(r"[\r\n\u0085  ]")


def _text(value: Any, maximum: int, path: str, found: dict[str, str]) -> str | None:
    """A text of 1 to `maximum` characters, else the reason recorded at `path`."""
    if value is None:
        found.setdefault(path, "required")
    elif not isinstance(value, str) or not value:
        found.setdefault(path, "format")
    elif len(value) > maximum:
        found.setdefault(path, "too_long")
    else:
        return value
    return None


def _cite(value: Any, path: str, found: dict[str, str]) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        found.setdefault(path, "format")
        return None
    for name in value:
        if name not in ("path", "line", "quote"):
            found.setdefault(f"{path}.{name}", "format")
    where = _text(value.get("path"), PATH_MAX, f"{path}.path", found)
    quote = _text(value.get("quote"), QUOTE_MAX, f"{path}.quote", found)
    if quote is not None and LINE_BREAK.search(quote):
        found.setdefault(f"{path}.quote", "format")  # a quote is one line
        quote = None
    line = value.get("line")
    if line is not None and (isinstance(line, bool) or not isinstance(line, int) or line < 1):
        found.setdefault(f"{path}.line", "format")
        line = None
        where = None
    if where is None or quote is None or any(p.startswith(path + ".") for p in found):
        return None
    return {"path": where, "line": line, "quote": quote}


def check(value: Any) -> tuple[dict[str, Any] | None, dict[str, str]]:
    """The review as it is stored (a cite's absent `line` is `null`), and the problems by path.
    The review is `None` when there is any."""
    found: dict[str, str] = {}
    if value is None:
        return None, {"review": "required"}
    if not isinstance(value, dict):
        return None, {"review": "format"}
    for name in value:
        if name not in ("subject", "head", "verdict", "cites"):
            found.setdefault(f"review.{name}", "format")
    subject = _text(value.get("subject"), SUBJECT_MAX, "review.subject", found)
    head = value.get("head")
    if head is None:
        found.setdefault("review.head", "required")
    elif not isinstance(head, str) or not HEAD.fullmatch(head):
        found.setdefault("review.head", "format")
    verdict = value.get("verdict")
    if verdict is None:
        found.setdefault("review.verdict", "required")
    elif verdict not in VERDICTS:
        found.setdefault("review.verdict", "format")
    cites = value.get("cites")
    stored: list[dict[str, Any]] = []
    if cites is None:
        found.setdefault("review.cites", "required")
    elif not isinstance(cites, list):
        found.setdefault("review.cites", "format")
    elif not cites:
        found.setdefault("review.cites", "too_few")
    elif len(cites) > CITES_MAX:
        found.setdefault("review.cites", "too_many")
    else:
        for index, cite in enumerate(cites):
            one = _cite(cite, f"review.cites.{index}", found)
            if one is not None:
                stored.append(one)
    if found:
        return None, found
    assert subject is not None
    return {"subject": subject, "head": head, "verdict": verdict, "cites": stored}, {}
