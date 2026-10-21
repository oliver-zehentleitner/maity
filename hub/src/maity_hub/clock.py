"""The hub's clock: the only time in the system (docs/api.md §1.2).

Tests replace `now` to move time; everything that dates or compares calls it.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

_source: Callable[[], datetime] = lambda: datetime.now(UTC)  # noqa: E731


def now() -> datetime:
    return _source()


def set_source(source: Callable[[], datetime]) -> None:
    global _source
    _source = source


def reset() -> None:
    set_source(lambda: datetime.now(UTC))


def rfc3339(moment: datetime, *, millis: bool = False) -> str:
    """`2026-10-21T13:41:10Z`, or with milliseconds for the server-time header."""
    moment = moment.astimezone(UTC)
    if millis:
        return moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")
