"""`Server-Timing` on the API's answers: how many statements an answer sent to the database,
how long they took, and how long the hub took in all, so a slow page can be split into its
calls and each call into database and the rest without access to the server's log.

A context variable holds the tally of the request being answered. The engines' cursor events
add to it; outside a request (a worker, a migration) there is none and they add nothing.
Only counts and durations: no route, no statement, no id. And only to the instance
admin's own signed-in session; for every API request, the same numbers go to the hub's log,
which only the operators read (`maity_hub.timing`: route pattern, status, count, durations
and the worker's pid, never the path, so the line adds no handle or id). A count or a
duration on anyone else's answer could tell them about data they cannot see (a person's
agents in a private project add statements to the same empty answer)."""

from __future__ import annotations

import contextvars
import logging
import os
import time
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Engine, event
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from maity_hub.request_stats import route_of

API = "/api/v1/"


@dataclass
class Tally:
    statements: int = 0
    db: float = 0.0  # seconds spent in statements
    shown: bool = False  # the caller is the instance admin's signed-in session


_TALLY: contextvars.ContextVar[Tally | None] = contextvars.ContextVar("timing", default=None)
_STARTED = "maity_timing_started"
log = logging.getLogger("maity_hub.timing")


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
    """The cursor events on each engine a request may use: the pool's, the write guard's and
    the health probe's own (the last two may be absent)."""
    for engine in engines:
        if engine is not None and not event.contains(engine, "before_cursor_execute", _before):
            event.listen(engine, "before_cursor_execute", _before)
            event.listen(engine, "after_cursor_execute", _after)


def admit(instance_admin: bool) -> None:
    """Called once the caller is a human signed in by cookie, with whether that human is the
    instance admin (read in the sign-in's own statement): only then does the answer carry the
    header. Outside the API (no tally) it does nothing."""
    tally = _TALLY.get()
    if tally is not None:
        tally.shown = bool(instance_admin)


def header(tally: Tally, total: float) -> bytes:
    """`db;dur=<ms>, sql;desc="n=<count>", total;dur=<ms>`."""
    return (
        f'db;dur={tally.db * 1000:.1f}, sql;desc="n={tally.statements}", '
        f"total;dur={total * 1000:.1f}"
    ).encode()


class ServerTiming:
    """Outermost, so the hub's own checks before a route count too. The values are those
    at the start of the answer: a long poll's wait counts in `total`, never in `db`.

    Only the instance admin's signed-in session gets the header (`admit`), on any status;
    an agent, a token, a stranger and a visitor never do."""

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
            if message["type"] == "http.response.start":
                total = time.perf_counter() - began
                log.info(
                    "route=%s status=%s sql=%d db_ms=%.1f total_ms=%.1f pid=%d",
                    route_of(scope),
                    message["status"],
                    tally.statements,
                    tally.db * 1000,
                    total * 1000,
                    os.getpid(),  # which worker, to tie a slow line to its process
                )
                if tally.shown:
                    value = header(tally, total)
                    headers = [*message["headers"], (b"server-timing", value)]
                    message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, receive, timed)
        finally:
            _TALLY.reset(token)
