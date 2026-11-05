"""Reading a request body: into one buffer, within one deadline (docs/api.md §1.7).

Both readers of a body use this: the middleware's, for every routed call, and the forge
webhook's (§17.4), which reads its own body before the middleware's loop.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from starlette.types import Receive

from maity_hub.errors import error_response

# The whole body arrives within this many seconds, or the call is `request_timeout` (§1.7): a
# body sent slowly holds its connection and the bytes read so far no longer than this. An
# attachment of 10 MiB takes about 84 seconds at 1 Mbit/s.
BODY_SECONDS = 120


class _Outcome:
    def __init__(self, name: str) -> None:
        self.name = name

    def __repr__(self) -> str:
        return self.name


TOO_LARGE = _Outcome("TOO_LARGE")
TIMED_OUT = _Outcome("TIMED_OUT")
LEFT = _Outcome("LEFT")  # the client disconnected


async def read(receive: Receive, cap: int) -> bytes | _Outcome:
    """The body, at most `cap` bytes; TOO_LARGE past it, TIMED_OUT past the deadline, LEFT
    when the client went away. Appended in place: `bytes +=` would copy everything read so
    far on each chunk."""
    buffer = bytearray()
    deadline = time.monotonic() + BODY_SECONDS
    more = True
    while more:
        try:
            message = await asyncio.wait_for(receive(), max(deadline - time.monotonic(), 0))
        except TimeoutError:
            return TIMED_OUT
        if message["type"] == "http.disconnect":
            return LEFT
        buffer += message.get("body", b"")
        more = message.get("more_body", False)
        if len(buffer) > cap:
            return TOO_LARGE
    return bytes(buffer)


def timed_out() -> Any:
    """The answer to a body that did not arrive in time; the rest of it may still be coming."""
    message = f"the body did not arrive within {BODY_SECONDS} seconds"
    return error_response(408, "request_timeout", message, headers={"Connection": "close"})
