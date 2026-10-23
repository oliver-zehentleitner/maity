"""The replies of a request (docs/api.md §7): its options, or go/no for a bare consent.

Apart from `inbox` so that what reads requests without the caller machinery (the
ticker's read path) can name a reply's label.
"""

from __future__ import annotations

from typing import Any

CONSENT_REPLIES = [{"id": "go", "label": "go"}, {"id": "no", "label": "no"}]


def replies(class_: str, options: list[dict[str, Any]]) -> list[dict[str, str]]:
    """The answers the inbox renders as buttons: the options, or go/no for a bare consent."""
    if class_ == "consent" and not options:
        return list(CONSENT_REPLIES)
    return [{"id": o["id"], "label": o["label"]} for o in options]
