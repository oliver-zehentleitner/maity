"""`Server-Timing` on the API's answers: how many statements an answer sent to the database,
how long they took, and how long the hub took in all, so a slow page can be split into its
calls and each call into database and the rest without access to the server's log.

A context variable holds the tally of the request being answered. The engines' cursor events
add to it; outside a request (a worker, a migration) there is none and they add nothing.
Only counts and durations: no route, no statement, no id."""

from __future__ import annotations

import contextvars
import time
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Engine, event
from starlette.types import ASGIApp, Message, Receive, Scope, Send

API = "/api/v1/"


@dataclass
class Tally:
    statements: int = 0
    db: float = 0.0  # seconds spent in statements


_TALLY: contextvars.ContextVar[Tally | None] = contextvars.ContextVar("timing", default=None)
_STARTED = "maity_timing_started"


def _before(conn: Any, cursor: Any, statement: Any, params: Any, context: Any, many: bool) -> None:
    tally = _TALLY.get()
    if tally is None:
        return
    tally.statements += 1
    if context is not None:
        setattr(context, _STARTED, time.perf_counter())


def _after(conn: Any, cursor: Any, statement: Any, params: Any, context: Any, many: bool) -> None:
    tally = _TALLY.get()
    started = getattr(context, _STARTED, None) if context is not None else None
    if tally is not None and started is not None:
        tally.db += time.perf_counter() - started


def install(*engines: Engine | None) -> None:
    """The cursor events on each engine a request may use (the shared one may be absent)."""
    for engine in engines:
        if engine is not None and not event.contains(engine, "before_cursor_execute", _before):
            event.listen(engine, "before_cursor_execute", _before)
            event.listen(engine, "after_cursor_execute", _after)


def header(tally: Tally, total: float) -> bytes:
    """`db;dur=<ms>, sql;desc="n=<count>", total;dur=<ms>`."""
    return (
        f'db;dur={tally.db * 1000:.1f}, sql;desc="n={tally.statements}", '
        f"total;dur={total * 1000:.1f}"
    ).encode()


class ServerTiming:
    """Outermost, so the hub's own checks before a route count too. The values are those
    at the start of the answer: a long poll's wait counts in `total`, never in `db`.

    Only a success or a redirect carries the header. A refusal does not: how many
    statements a 403 or a 404 took could tell a project or an account that exists from
    one that does not."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not str(scope.get("path", "")).startswith(API):
            await self.app(scope, receive, send)
            return
        tally = Tally()
        token = _TALLY.set(tally)
        began = time.perf_counter()

        async def timed(message: Message) -> None:
            if message["type"] == "http.response.start" and message["status"] < 400:
                value = header(tally, time.perf_counter() - began)
                message = {**message, "headers": [*message["headers"], (b"server-timing", value)]}
            await send(message)

        try:
            await self.app(scope, receive, timed)
        finally:
            _TALLY.reset(token)
