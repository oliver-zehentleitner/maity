"""UTC timestamps in the wire form of §1.1: whole seconds and a trailing `Z`."""

from __future__ import annotations

import re
import time
from datetime import UTC, datetime

FORMAT = "%Y-%m-%dT%H:%M:%SZ"
# Exact wire form only: uppercase T and Z, no fraction, no offset.
WIRE_TIMESTAMP = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z")


def stamp(moment: float | datetime | None = None) -> str:
    """`moment` as UTC to the second, with a trailing `Z`. A float is seconds since the
    epoch; a datetime is converted with `astimezone` (a naive value is local time, as
    `datetime.astimezone` does); None is now."""
    if moment is None:
        moment = time.time()
    if isinstance(moment, datetime):
        at = moment.astimezone(UTC)
    else:
        at = datetime.fromtimestamp(moment, tz=UTC)
    return at.strftime(FORMAT)


def parse_stamp(value: object, *, strict: bool = False) -> datetime | None:
    """A timestamp as a timezone-aware datetime, or None.

    A non-string, a value `fromisoformat` rejects, a naive result (no offset and no
    `Z`), or a time that overflows when converted to UTC is None. A successful result
    is in UTC. `strict=True` also requires the wire form `YYYY-MM-DDTHH:MM:SSZ` (no
    fraction, offset, space, or lowercase). Python 3.11's `fromisoformat` already accepts
    a trailing `Z`, so this does not rewrite `Z` to `+00:00`.
    """
    if not isinstance(value, str):
        return None
    if strict and not WIRE_TIMESTAMP.fullmatch(value):
        return None
    try:
        at = datetime.fromisoformat(value)
    except (ValueError, OverflowError):
        return None
    if at.tzinfo is None:
        return None
    try:
        return at.astimezone(UTC)
    except OverflowError:
        return None
