"""No `async def` in the hub runs a sync database transaction on the event loop.

On SQLite every transaction begins IMMEDIATE, and every request's authentication
(deps.authenticated) is an async-engine transaction that holds the write lock across awaits.
A sync transaction started on the loop thread waits for that lock while blocking the loop the
holder needs to commit, so it gives up after the busy timeout and the request answers 503
(web-e2e on #1843: `POST /admin/reports/{id}/resolve`, total_ms=5014, loop_late_max_ms=4925).
Such work goes through `run_in_threadpool` (routes/auth.py) or a plain `def` route; calls
inside a nested sync function are what that function's runner decides, so they are not
flagged here. KTW: hub/context/persistence.md, 09716491-b10a-4c73-bf6e-cfe0eabba8ba."""

from __future__ import annotations

import ast
from pathlib import Path

import maity_hub

PACKAGE = Path(maity_hub.__file__).parent

# Calls that run a sync transaction: `idempotency.run(engine, ...)`, `events.transaction(engine)`
# and `retrying(work)` (db.retrying, imported bare or as `db.retrying`).
SYNC_CALLS = {"idempotency.run", "events.transaction", "retrying", "db.retrying"}
# `with <x>.begin()` / `with <x>.connect()` without `async`: a sync engine's transaction.
SYNC_CONTEXTS = {"begin", "connect"}


def _name(call: ast.Call) -> str:
    return ast.unparse(call.func)


def _sync_db_calls(fn: ast.AsyncFunctionDef) -> list[tuple[int, str]]:
    """The sync transactions `fn` runs itself, outside nested functions and not awaited."""
    found: list[tuple[int, str]] = []
    awaited: set[int] = set()
    stack: list[ast.AST] = list(fn.body)
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue
        if isinstance(node, ast.Await):
            awaited.add(id(node.value))
        if isinstance(node, ast.With):
            for item in node.items:
                expr = item.context_expr
                if (
                    isinstance(expr, ast.Call)
                    and isinstance(expr.func, ast.Attribute)
                    and expr.func.attr in SYNC_CONTEXTS
                ):
                    found.append((node.lineno, f"with {ast.unparse(expr)}"))
        if isinstance(node, ast.Call) and id(node) not in awaited and _name(node) in SYNC_CALLS:
            found.append((node.lineno, f"{_name(node)}(...)"))
        stack.extend(ast.iter_child_nodes(node))
    return sorted(found)


def offenders(source: str, label: str) -> list[str]:
    tree = ast.parse(source)
    return [
        f"{label}:{line} {fn.name} runs {what} on the event loop"
        for fn in ast.walk(tree)
        if isinstance(fn, ast.AsyncFunctionDef)
        for line, what in _sync_db_calls(fn)
    ]


def test_no_async_def_runs_a_sync_transaction_on_the_loop() -> None:
    found = [
        offence
        for path in sorted(PACKAGE.rglob("*.py"))
        for offence in offenders(path.read_text(), str(path.relative_to(PACKAGE)))
    ]
    assert not found, "use run_in_threadpool (or a plain def route):\n" + "\n".join(found)


def test_the_scan_catches_what_it_should_and_nothing_else() -> None:
    source = """
async def bad(request, caller, action):
    with engine_of(request).begin() as conn:
        pass
    with engine.connect() as conn:
        pass
    with events.transaction(engine) as conn:
        pass
    retrying(work)
    return idempotency.run(engine_of(request), request, caller, action)

async def good(request, caller, action):
    async with async_engine.begin() as conn:
        await conn.run_sync(work)
    async with events.async_transaction(engine) as conn:
        pass

    def run():
        with engine.begin() as conn:
            retrying(work)
        return idempotency.run(engine, request, caller, action)

    await run_in_threadpool(run)
    return await run_in_threadpool(idempotency.run, engine, request, caller, action)

def plain(request, caller, action):
    return idempotency.run(engine_of(request), request, caller, action)
"""
    assert offenders(source, "x.py") == [
        "x.py:3 bad runs with engine_of(request).begin() on the event loop",
        "x.py:5 bad runs with engine.connect() on the event loop",
        "x.py:7 bad runs events.transaction(...) on the event loop",
        "x.py:9 bad runs retrying(...) on the event loop",
        "x.py:10 bad runs idempotency.run(...) on the event loop",
    ]
