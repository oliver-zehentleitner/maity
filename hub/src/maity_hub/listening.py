"""Which sessions hold an open events long-poll right now (docs/api.md §5.3, §8.3).

In-process, for one replica; the long-poll (events slice) registers here.
"""

from __future__ import annotations

import threading

_open: dict[str, int] = {}
_lock = threading.Lock()


def is_listening(session_id: str) -> bool:
    with _lock:
        return _open.get(session_id, 0) > 0


def opened(session_id: str) -> None:
    with _lock:
        _open[session_id] = _open.get(session_id, 0) + 1


def closed(session_id: str) -> None:
    with _lock:
        remaining = _open.get(session_id, 0) - 1
        if remaining > 0:
            _open[session_id] = remaining
        else:
            _open.pop(session_id, None)
