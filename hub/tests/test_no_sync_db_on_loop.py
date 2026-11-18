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


Key = tuple[str, str]  # (module, function), (module, "Class.method") or (module, "Class")


class Module:
    def __init__(self, name: str, tree: ast.Module, modules: set[str]) -> None:
        self.name = name
        self.tree = tree
        self.functions: dict[str, ast.FunctionDef | ast.AsyncFunctionDef] = {}
        self.classes: set[str] = set()
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self.functions[node.name] = node
            elif isinstance(node, ast.ClassDef):
                self.classes.add(node.name)
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        self.functions[f"{node.name}.{item.name}"] = item
        # Local name -> a module of the package, or (module, name) of the package.
        self.modules: dict[str, str] = {}
        self.imported: dict[str, Key] = {}
        for imp in ast.walk(tree):
            if isinstance(imp, ast.Import):
                for alias in imp.names:
                    if alias.name in modules and alias.asname:
                        self.modules[alias.asname] = alias.name
            elif isinstance(imp, ast.ImportFrom) and imp.module and imp.level == 0:
                for alias in imp.names:
                    local = alias.asname or alias.name
                    full = f"{imp.module}.{alias.name}"
                    if full in modules:
                        self.modules[local] = full
                    elif imp.module in modules:
                        self.imported[local] = (imp.module, alias.name)
        # Objects of the package's classes: module-level names and `self.<attr>` of a class.
        self.instances: dict[str, Key] = {}
        self.attributes: dict[tuple[str, str], Key] = {}  # (class, attr) -> class


class Package:
    def __init__(self, sources: dict[str, str]) -> None:
        names = set(sources)
        self.modules = {
            name: Module(name, ast.parse(text), names) for name, text in sources.items()
        }
        for module in self.modules.values():
            for node in module.tree.body:
                if isinstance(node, (ast.Assign, ast.AnnAssign)):
                    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                    made = self._made(module, node.value)
                    for target in targets:
                        if made is not None and isinstance(target, ast.Name):
                            module.instances[target.id] = made
                elif isinstance(node, ast.ClassDef):
                    for sub in ast.walk(node):
                        if isinstance(sub, ast.Assign):
                            made = self._made(module, sub.value)
                            for target in sub.targets:
                                if (
                                    made is not None
                                    and isinstance(target, ast.Attribute)
                                    and isinstance(target.value, ast.Name)
                                    and target.value.id == "self"
                                ):
                                    module.attributes[(node.name, target.attr)] = made

    def _class(self, module: Module, expr: ast.expr) -> Key | None:
        """The package class `expr` names."""
        key: Key | None = None
        if isinstance(expr, ast.Name):
            key = (
                (module.name, expr.id)
                if expr.id in module.classes
                else module.imported.get(expr.id)
            )
        elif (
            isinstance(expr, ast.Attribute)
            and isinstance(expr.value, ast.Name)
            and (other := module.modules.get(expr.value.id)) is not None
        ):
            key = (other, expr.attr)
        if key is not None and key[0] in self.modules and key[1] in self.modules[key[0]].classes:
            return key
        return None

    def _made(self, module: Module, value: ast.expr | None) -> Key | None:
        """The class of the object `value` makes, unless it is a limiter counted in this
        process only (`local=True`), which never reaches the database."""
        if not isinstance(value, ast.Call):
            return None
        for keyword in value.keywords:
            if (
                keyword.arg == "local"
                and isinstance(keyword.value, ast.Constant)
                and keyword.value.value is True
            ):
                return None
        return self._class(module, value.func)

    def _object(self, module: Module, expr: ast.expr, owner: str | None) -> Key | None:
        """The class of the object `expr` names: a module-level object of this module or
        another, `self` in a method, or an object in an attribute of `self`."""
        if isinstance(expr, ast.Name):
            if expr.id == "self" and owner is not None:
                return (module.name, owner)
            if expr.id in module.instances:
                return module.instances[expr.id]
            if (source := module.imported.get(expr.id)) is not None and source[0] in self.modules:
                return self.modules[source[0]].instances.get(source[1])
        if isinstance(expr, ast.Attribute) and isinstance(expr.value, ast.Name):
            if expr.value.id == "self" and owner is not None:
                return module.attributes.get((owner, expr.attr))
            if (other := module.modules.get(expr.value.id)) is not None:
                return self.modules[other].instances.get(expr.attr)
        return None

    def resolve(self, module: Module, call: ast.Call, owner: str | None) -> Key | None:
        """The package function or method a call names, if it names one."""
        func = call.func
        if isinstance(func, ast.Name):
            if func.id in module.functions:
                return (module.name, func.id)
            return module.imported.get(func.id)
        if isinstance(func, ast.Attribute):
            cls = self._object(module, func.value, owner)
            if cls is not None:
                return (cls[0], f"{cls[1]}.{func.attr}")
            if (
                isinstance(func.value, ast.Name)
                and (other := module.modules.get(func.value.id)) is not None
            ):
                return (other, func.attr)
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


def _owner(key: Key) -> str | None:
    return key[1].rsplit(".", 1)[0] if "." in key[1] else None


def _scan(sources: dict[str, str]) -> list[str]:
    """`sources` maps a module's dotted name to its text; the offences of every `async def`."""
    package = Package(sources)
    functions = {
        (module.name, name): fn
        for module in package.modules.values()
        for name, fn in module.functions.items()
    }
    # Sync functions and methods that open a transaction, directly or through another one.
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
                    callee = package.resolve(package.modules[key[0]], node, _owner(key))
                    if callee is not None and callee in opens and callee != key:
                        opens[key] = f"{callee[1]}(...) -> {opens[callee]}"
                        changed = True
                        break

    found = []
    for key, coroutine in functions.items():
        if not isinstance(coroutine, ast.AsyncFunctionDef):
            continue
        if (key[0].rsplit(".", 1)[-1], key[1]) in STARTUP:
            continue
        module = package.modules[key[0]]
        for node in _own_nodes(coroutine):
            what = _direct(node)
            if what is None and isinstance(node, ast.Call):
                callee = package.resolve(module, node, _owner(key))
                if callee is not None and callee in opens:
                    what = f"{callee[1]}(...) -> {opens[callee]}"
            if what is not None:
                found.append((key[0], getattr(node, "lineno", 0), key[1], what))
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


def test_the_scan_follows_methods_of_the_package_s_objects() -> None:
    limits = """
class Limiter:
    def __init__(self, limit, *, name, local=False):
        self.local = local

    def hit(self, key):
        return self.take(key, 1)

    def take(self, key, count):
        if not self.local:
            return self._shared(key, count)
        return 0

    def _shared(self, key, count):
        with _db().begin() as conn:
            return 0

    def size(self):
        return 0
"""
    routes = """
from pkg import limits
from pkg.limits import Limiter

BY_ADDRESS = Limiter(10, name="a")
IN_PROCESS = Limiter(10, name="b", local=True)
OTHER = limits.Limiter(10, name="c")


class Pair:
    def __init__(self):
        self.by_source = Limiter(10, name="d")

    def take(self, key):
        return self.by_source.hit(key)


PAIRS = Pair()


async def bad(request):
    BY_ADDRESS.hit(request)
    OTHER.take(request, 2)
    PAIRS.take(request)

async def good(request):
    await run_in_threadpool(BY_ADDRESS.hit, request)
    IN_PROCESS.hit(request)
    BY_ADDRESS.size()
    unknown.hit(request)
"""
    assert _scan({"pkg.limits": limits, "pkg.routes": routes}) == [
        "pkg.routes:22 bad runs Limiter.hit(...) -> Limiter.take(...) -> Limiter._shared(...)"
        " -> with _db().begin() on the event loop",
        "pkg.routes:23 bad runs Limiter.take(...) -> Limiter._shared(...)"
        " -> with _db().begin() on the event loop",
        "pkg.routes:24 bad runs Pair.take(...) -> Limiter.hit(...) -> Limiter.take(...)"
        " -> Limiter._shared(...) -> with _db().begin() on the event loop",
    ]
