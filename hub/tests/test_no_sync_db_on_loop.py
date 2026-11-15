"""No `async def` in the hub runs a sync database transaction on the event loop.

On SQLite every transaction begins IMMEDIATE, and every request's authentication
(deps.authenticated) is an async-engine transaction that holds the write lock across awaits.
A sync transaction started on the loop thread waits for that lock while blocking the loop the
holder needs to commit, so it gives up after the busy timeout and the request answers 503
(web-e2e on #1843: `POST /admin/reports/{id}/resolve`, total_ms=5014, loop_late_max_ms=4925).
Such work goes through `run_in_threadpool` (routes/auth.py) or a plain `def` route; calls
inside a nested sync function are what that function's runner decides, so they are not
flagged here. A call of a module-level sync function of the package counts as what that
function runs, transitively (`device_codes._require_enabled`, review of #1845).
KTW: hub/context/persistence.md, 09716491-b10a-4c73-bf6e-cfe0eabba8ba."""

from __future__ import annotations

import ast
from collections.abc import Iterator
from pathlib import Path

import maity_hub

PACKAGE = Path(maity_hub.__file__).parent

# Calls that run a sync transaction: `idempotency.run(engine, ...)`, `events.transaction(engine)`
# and `retrying(work)` (db.retrying, imported bare or as `db.retrying`). Most are found through
# their bodies as well; `retrying` runs a callable it is given, so it is named here.
SYNC_CALLS = {"idempotency.run", "events.transaction", "retrying", "db.retrying"}
# `with <x>.begin()` / `with <x>.connect()` without `async`: a sync engine's transaction.
SYNC_CONTEXTS = {"begin", "connect"}
# Startup and shutdown run before the first request and after the last; nothing on the loop
# can hold the write lock then.
STARTUP = {("app", "lifespan")}

Key = tuple[str, str]  # (module, function)


def _own_nodes(fn: ast.AST) -> Iterator[ast.AST]:
    """The nodes of `fn`'s body, without those of nested functions and lambdas, and without
    the calls it awaits."""
    awaited: set[int] = set()
    stack: list[ast.AST] = list(getattr(fn, "body", []))
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue
        if isinstance(node, ast.Await):
            awaited.add(id(node.value))
        if not (isinstance(node, ast.Call) and id(node) in awaited):
            yield node
        stack.extend(ast.iter_child_nodes(node))


class Module:
    def __init__(self, name: str, tree: ast.Module, modules: set[str]) -> None:
        self.name = name
        self.tree = tree
        self.functions = {
            node.name: node
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        # Local name -> a module of the package, or (module, function) of the package.
        self.modules: dict[str, str] = {}
        self.imported: dict[str, Key] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name in modules and alias.asname:
                        self.modules[alias.asname] = alias.name
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                for alias in node.names:
                    local = alias.asname or alias.name
                    full = f"{node.module}.{alias.name}"
                    if full in modules:
                        self.modules[local] = full
                    elif node.module in modules:
                        self.imported[local] = (node.module, alias.name)

    def resolve(self, call: ast.Call) -> Key | None:
        """The package function a call names, if it names one."""
        func = call.func
        if isinstance(func, ast.Name):
            if func.id in self.functions:
                return (self.name, func.id)
            return self.imported.get(func.id)
        if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
            module = self.modules.get(func.value.id)
            if module is not None:
                return (module, func.attr)
        return None


def _direct(node: ast.AST) -> str | None:
    """What `node` itself runs synchronously, if it opens a transaction."""
    if isinstance(node, ast.With):
        for item in node.items:
            expr = item.context_expr
            if (
                isinstance(expr, ast.Call)
                and isinstance(expr.func, ast.Attribute)
                and expr.func.attr in SYNC_CONTEXTS
            ):
                return f"with {ast.unparse(expr)}"
    if isinstance(node, ast.Call) and ast.unparse(node.func) in SYNC_CALLS:
        return f"{ast.unparse(node.func)}(...)"
    return None


def _scan(sources: dict[str, str]) -> list[str]:
    """`sources` maps a module's dotted name to its text; the offences of every `async def`."""
    names = set(sources)
    modules = {name: Module(name, ast.parse(text), names) for name, text in sources.items()}
    functions = {
        (module.name, fn_name): fn
        for module in modules.values()
        for fn_name, fn in module.functions.items()
    }
    # Sync functions that open a transaction, directly or through another such function.
    opens: dict[Key, str] = {}
    for key, fn in functions.items():
        if isinstance(fn, ast.FunctionDef):
            for node in _own_nodes(fn):
                if (what := _direct(node)) is not None:
                    opens[key] = what
                    break
    changed = True
    while changed:
        changed = False
        for key, fn in functions.items():
            if key in opens or not isinstance(fn, ast.FunctionDef):
                continue
            for node in _own_nodes(fn):
                if isinstance(node, ast.Call):
                    callee = modules[key[0]].resolve(node)
                    if callee in opens and callee != key:
                        opens[key] = f"{callee[1]}(...) -> {opens[callee]}"
                        changed = True
                        break

    found = []
    for module in modules.values():
        for coroutine in ast.walk(module.tree):
            if not isinstance(coroutine, ast.AsyncFunctionDef):
                continue
            if (module.name.rsplit(".", 1)[-1], coroutine.name) in STARTUP:
                continue
            for node in _own_nodes(coroutine):
                what = _direct(node)
                if what is None and isinstance(node, ast.Call):
                    callee = module.resolve(node)
                    if callee in opens:
                        what = f"{callee[1]}(...) -> {opens[callee]}"
                if what is not None:
                    found.append((module.name, getattr(node, "lineno", 0), coroutine.name, what))
    return [
        f"{name}:{line} {fn_name} runs {what} on the event loop"
        for name, line, fn_name, what in sorted(found)
    ]


def _package_sources() -> dict[str, str]:
    sources = {}
    for path in sorted(PACKAGE.rglob("*.py")):
        parts = ("maity_hub", *path.relative_to(PACKAGE).with_suffix("").parts)
        if parts[-1] == "__init__":
            parts = parts[:-1]
        sources[".".join(parts)] = path.read_text()
    return sources


def test_no_async_def_runs_a_sync_transaction_on_the_loop() -> None:
    found = _scan(_package_sources())
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
    assert _scan({"x": source}) == [
        "x:3 bad runs with engine_of(request).begin() on the event loop",
        "x:5 bad runs with engine.connect() on the event loop",
        "x:7 bad runs events.transaction(...) on the event loop",
        "x:9 bad runs retrying(...) on the event loop",
        "x:10 bad runs idempotency.run(...) on the event loop",
    ]


def test_the_scan_follows_sync_helpers_of_the_package() -> None:
    helpers = """
def opens(engine):
    with engine.begin() as conn:
        return conn

def through(engine):
    return opens(engine)

def harmless(engine):
    def later():
        with engine.begin():
            pass
    return later
"""
    routes = """
from pkg import helpers
from pkg.helpers import through as also

def _require(request):
    with engine_of(request).begin() as conn:
        pass

async def bad(request):
    _require(request)
    helpers.opens(engine)
    also(engine)

async def good(request):
    await run_in_threadpool(_require, request)
    await run_in_threadpool(helpers.through, engine)
    helpers.harmless(engine)
    other.opens(engine)

    def read():
        return _require(request)

    return await run_in_threadpool(read)
"""
    assert _scan({"pkg.helpers": helpers, "pkg.routes": routes}) == [
        "pkg.routes:10 bad runs _require(...) -> with engine_of(request).begin() on the event loop",
        "pkg.routes:11 bad runs opens(...) -> with engine.begin() on the event loop",
        "pkg.routes:12 bad runs through(...) -> opens(...) -> with engine.begin()"
        " on the event loop",
    ]
