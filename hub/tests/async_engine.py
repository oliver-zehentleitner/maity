"""The async engine in tests (tsk-v874y63b4z8p): one beside the test's sync engine, on the same
database, with the hooks a serving hub gives it, for as long as one coroutine runs.

An async engine's pooled connections belong to the event loop that opened them, so the engine is
made, used and disposed inside the same `asyncio.run`."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from sqlalchemy import Engine
from sqlalchemy.ext.asyncio import AsyncEngine

from maity_hub import timing, write_guard
from maity_hub.db import make_async_engine


def on_async_engine[T](engine: Engine, work: Callable[[AsyncEngine], Awaitable[T]]) -> T:
    """`work` with an async engine on `engine`'s database, `write_guard` and `timing` on its
    `sync_engine` as `create_app` installs them; disposed before this returns."""

    async def main() -> T:
        async_engine = make_async_engine(engine.url)
        write_guard.install(async_engine.sync_engine)
        timing.install(async_engine.sync_engine)
        try:
            return await work(async_engine)
        finally:
            await async_engine.dispose()

    return asyncio.run(main())
