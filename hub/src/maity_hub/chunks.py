"""What one IN list carries at most, for every read that names many ids or paths at once.

A leaf module: it imports nothing of the hub, so any module can use it without an import
cycle (the export, the abuse reports and the public pages each kept a copy of the bound
before, because `export` imports `reports`, which imports `moderation`, which imports
`public_projects`).
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator

# Far below every engine's limit on bound parameters (SQLite's is usually 32766, PostgreSQL's
# 65535), and above the ids of a normal list, so a list still asks each question in one
# statement. Read at each call, so a test may lower it.
CHUNK = 500


def chunks[T](values: Iterable[T]) -> Iterator[list[T]]:
    """`values` without repeats, sorted, in lists of at most `CHUNK`."""
    items = sorted(set(values), key=str)
    for start in range(0, len(items), CHUNK):
        yield items[start : start + CHUNK]
