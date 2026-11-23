"""The e2e harness's own judgement of answers, without a browser or a hub.

e2e.py imports Playwright at the top; this reads only the parts it tests out of
the file's syntax tree (no_problems, the trace) and runs them
on stand-in answers. Python standard library only: python3 web/tools/test_e2e_harness.py
"""

import ast
import contextlib
import email
import email.policy
import fcntl
import http.client
import io
import json
import os
import re
import socket
import socketserver
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from email.message import EmailMessage
from pathlib import Path

SOURCE = Path(__file__).with_name("e2e.py")
WANTED = {
    "no_problems",
    "TRACE_BODY", "TRACE_ROUTE", "TRACE_ENUMS", "TRACE_CODES", "TRACE_ID",
    "trace_path", "trace_data", "trace_line", "report_failure",
    "clean_environment",
    "LOCK_PATH", "_machine_lock", "open_lock_file", "take_machine_lock",
    "BOOT_HEAD", "BootHeads",
    "free_port", "port_taken", "MailCatcher",
}


def load() -> dict:
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    nodes = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name in WANTED:
            nodes.append(node)
        elif isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id in WANTED for t in node.targets):
            nodes.append(node)
    found = {n.name if isinstance(n, (ast.FunctionDef, ast.ClassDef)) else n.targets[0].id for n in nodes}
    if found != WANTED:
        sys.exit(f"e2e.py lacks {sorted(WANTED - found)}")
    namespace = {
        "re": re, "json": json, "sys": sys, "Path": Path, "Run": object, "os": os, "fcntl": fcntl,
        "time": time, "socket": socket, "socketserver": socketserver, "threading": threading,
        "email": email, "EmailMessage": EmailMessage,
    }
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(SOURCE), "exec"), namespace)
    return namespace


BASE = "http://127.0.0.1:9"


class Request:
    def __init__(self, method: str):
        self.method = method


class FakeRun:
    def __init__(self, problems):
        self.base = BASE
        self.problems = list(problems)


def problems(ns: dict, said) -> list[str]:
    run = FakeRun(said)
    try:
        ns["no_problems"](run, "test")
    except AssertionError:
        pass
    return run.problems


class Raw:
    """A stand-in for a Response whose body is raw text."""

    def __init__(self, method: str, path: str, status: int, text: str | None):
        self.request = Request(method)
        self.url = BASE + path
        self.status = status
        self._text = text

    def text(self) -> str:
        if self._text is None:
            raise RuntimeError("gone")
        return self._text


# Synthetic markers that must never reach the trace, by where they sit.
SECRETS = ["lowercasesecret", "secret-deadbeef", "TEST-CODE-ONLY", "JOINTOKENabc123", "PAIRTOKENxyz789", "QUERYTOKENq1", "CODE-AAAA-BBBB", "CREDmty1.rcrd-SECRET", "NESTEDsecret42", "PLAINTEXTsecret"]


def trace_cases(ns: dict) -> int:
    failed = 0

    def check(name: str, ok: bool, detail: object = "") -> None:
        nonlocal failed
        failed += not ok
        print(("ok   " if ok else "FAIL ") + name + ("" if ok else f": {detail}"))

    answers = [
        Raw("GET", "/api/v1/join/JOINTOKENabc123", 200, json.dumps({"x": "y"})),
        Raw("POST", "/api/v1/runners/pair/PAIRTOKENxyz789", 201, "CREDmty1.rcrd-SECRET"),
        Raw("GET", "/api/v1/runners?token=QUERYTOKENq1&limit=5", 200, json.dumps({"items": [
            {"id": "rnr-abc123def", "name": "e2e-renamed", "presence": "offline", "credential_state": "active",
             "credential": {"id": "rcrd-1234abcd", "value": "CREDmty1.rcrd-SECRET"},
             "extra": {"deep": {"token": "NESTEDsecret42", "state": "ok"}}}]})),
        Raw("POST", "/api/v1/runners/enrollments", 201, json.dumps(
            {"id": "enr-1", "code": "CODE-AAAA-BBBB", "pair_url": "http://h/pair/PAIRTOKENxyz789"})),
        Raw("GET", "/api/v1/me", 403, json.dumps({"error": {"code": "forbidden", "message": "PLAINTEXTsecret"}})),
        Raw("GET", "/api/v1/me/notifications", 200, "PLAINTEXTsecret"),
        Raw("GET", "/api/v1/gone", 200, None),
        Raw("GET", "/api/v1/unknown/secret-deadbeef", 200, None),
        Raw("GET", "/api/v1/JOIN/lowercasesecret", 200, None),
        Raw("GET", "/api/v1/%6aoin/lowercasesecret", 200, None),
        Raw("GET", "/api/v1/join/%4AOIN-lowercasesecret", 200, json.dumps(
            {"name": "https://h/join/lowercasesecret", "lowercasesecret": {"state": "active"},
             "state": "lowercasesecret", "id": "lowercasesecret",
             "error": {"code": "TEST-CODE-ONLY"}})),
    ]
    with tempfile.TemporaryDirectory() as tmp:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stderr(err):
            trace = ns["report_failure"](answers, BASE, Path(tmp))
        written = (Path(tmp) / "api-trace.txt").read_text()
    for target, text in (("api-trace.txt", written), ("stderr", err.getvalue()), ("return value", trace)):
        leaked = [m for m in SECRETS if m in text]
        check(f"no secret reaches {target}", not leaked, leaked)
    lines = trace.splitlines()
    check("one line per answer", len(lines) == len(answers), len(lines))
    check("a token path is masked, the query is dropped", lines[0].startswith("GET /api/v1/join/{} 200") and "?" not in lines[2].split(" ")[1], lines[:3])
    check("an unknown or re-spelled route shows no segment", all(l.split(" ")[1].replace("{}", "").strip("/").count("secret") == 0 for l in lines[7:]) and lines[7].startswith("GET /api/v1/{}/{} 200") and lines[8].startswith("GET /api/v1/{}/{} 200"), lines[7:])
    check("the runner's state is kept", '"credential_state":"active"' in lines[2] and '"presence":"offline"' in lines[2] and "rnr-abc123def" in lines[2], lines[2])
    check("a nested secret and any other key are dropped", "NESTED" not in lines[2] and "extra" not in lines[2] and "credential\"" not in lines[2], lines[2])
    check("an unlisted value or code is shown as ?", '"state":"?"' in lines[10] and '"id":"?"' in lines[10] and '"code":"?"' in lines[10] and "name" not in lines[10], lines[10])
    check("an error keeps its code, not its message", '"code":"forbidden"' in lines[4] and "message" not in lines[4], lines[4])
    check("an enrollment keeps no code", '"code"' not in lines[3], lines[3])
    check("a body that is not JSON, or gone, is not shown", lines[1].endswith("(body not shown)") and lines[5].endswith("(body not shown)") and lines[6].endswith("(body not shown)"), lines)
    return failed


def boot_head_cases(ns: dict) -> int:
    """The boot's early notifications head (BootHeads, tsk-zf3wd9t5gjab): its 401 or 403 is excused only
    while that page's /bootstrap is out; a later head's refusal stays a problem."""
    failed = 0

    def check(name: str, ok: bool) -> None:
        nonlocal failed
        failed += not ok
        print(("ok   " if ok else "FAIL ") + name)

    head, boot = ns["BOOT_HEAD"], "/api/v1/bootstrap?project=owner/e2e-alpha"
    heads = ns["BootHeads"]()
    early, late, other = object(), object(), object()
    heads.asked(boot, object())
    heads.asked(head, early)
    heads.asked("/api/v1/me", other)
    heads.ended(boot)
    heads.asked(head, late)
    check("boot head: a 401 of the head asked beside /bootstrap is excused", heads.excused(head, 401, early))
    check("boot head: a 403 of it too (a session that owes the second factor)", heads.excused(head, 403, early))
    check("boot head: a 503 of it too (a running maintenance window)", heads.excused(head, 503, early))
    check("boot head: its 500 stays a problem", not heads.excused(head, 500, early))
    check("boot head: a head asked after /bootstrap answered stays a problem", not heads.excused(head, 401, late))
    check("boot head: another route asked beside /bootstrap stays a problem", not heads.excused("/api/v1/me", 401, other))
    check("boot head: with no /bootstrap out nothing is excused", not ns["BootHeads"]().excused(head, 401, early))
    heads.ended(head, early)
    check("boot head: an early head is forgotten once it answered", early not in heads.early and not heads.excused(head, 401, early))
    return failed


def unscoped_processes() -> list[int]:
    """The lines of e2e.py that start a process without naming its environment."""
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    return [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "subprocess"
        and node.func.attr in {"run", "Popen", "call", "check_call", "check_output"}
        and not any(k.arg == "env" for k in node.keywords)
    ]


def environment_cases(ns: dict) -> int:
    environ = {"PATH": "/bin", "MAITY_STATE_DIR": "/real/agent", "MAITY_HUB": "https://real"}
    clean = ns["clean_environment"](environ)
    unscoped = unscoped_processes()
    failed = 0
    for name, ok, seen in [
        ("the returned environment holds no MAITY_ setting", clean == {"PATH": "/bin"}, clean),
        ("nor does the process's own, which Playwright inherits", environ == {"PATH": "/bin"}, environ),
        ("every process names its environment", not unscoped, unscoped),
    ]:
        failed += not ok
        print(("ok   " if ok else "FAIL ") + name + ("" if ok else f": {seen}"))
    return failed


HOLD = """
import fcntl, os, sys
d = os.open(sys.argv[1], os.O_RDWR | os.O_CREAT, 0o666)
fcntl.flock(d, fcntl.LOCK_EX)
os.pwrite(d, str(os.getpid()).encode(), 0)
print("held", flush=True)
sys.stdin.readline()
"""


def lock_cases(ns: dict) -> int:
    """It waits for a holder, names it, goes on once it ends, and takes the lock only once."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "lock"
        holder = subprocess.Popen(
            [sys.executable, "-c", HOLD, str(path)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, env={},
        )
        holder.stdout.readline()
        said = []
        say = lambda line, flush=False: said.append(line)
        # The holder ends with a kill, as a crashed run does: the lock must not outlive it.
        threading.Timer(0.3, holder.kill).start()
        ns["take_machine_lock"](path, say, every=0, pause=0.02)
        holder.wait()
        first = ns["_machine_lock"]
        cases = [
            ("the lock: waits for a holder and names it", any(f"pid {holder.pid}" in x for x in said)),
            ("the lock: goes on once the holder is gone, however it ended", first is not None),
            ("the lock: says who holds it now", path.read_text() == str(os.getpid())),
        ]
        ns["take_machine_lock"](path, say, every=0, pause=0.02)
        cases.append(("the lock: a second hub of the same run takes it no further", ns["_machine_lock"] == first))
        os.close(first)
        ns["_machine_lock"] = None
        # An existing file, possibly another user's, is opened without O_CREAT (fs.protected_regular).
        flags = []
        real_open = os.open
        os.open = lambda p, f, *a: (flags.append(f), real_open(p, f, *a))[1]
        try:
            os.close(ns["open_lock_file"](path))
            fresh = Path(tmp) / "fresh"
            os.close(ns["open_lock_file"](fresh))
        finally:
            os.open = real_open
        cases.append(("the lock: an existing file is opened without O_CREAT", not flags[0] & os.O_CREAT))
        cases.append(("the lock: a new file is open to every user", fresh.stat().st_mode & 0o777 == 0o666))
    for name, ok in cases:
        print(("ok   " if ok else "FAIL ") + name)
    return sum(not ok for _, ok in cases)


class FakePage:
    """What Run.a11y asks of a page: its viewport, the colour scheme it emulates, axe answering
    with no violations. It records every viewport and scheme it is given."""

    def __init__(self, width: int, height: int, scheme: str):
        self.viewport_size = {"width": width, "height": height}
        self.start = (width, height)
        self.scheme = scheme
        self.sizes, self.schemes = [], []

    def set_viewport_size(self, size: dict) -> None:
        # The restore is the one call back to the step's own size, which no pass uses.
        if getattr(self, "refuse", None) in ("viewport", "both") and (size["width"], size["height"]) == self.start:
            raise RuntimeError("viewport refused")
        self.viewport_size = dict(size)
        self.sizes.append((size["width"], size["height"]))

    def emulate_media(self, color_scheme: str | None = None, **_: object) -> None:
        refuse = getattr(self, "refuse", None)
        restoring = (self.viewport_size["width"], self.viewport_size["height"]) == self.start or (refuse == "both" and getattr(self, "runs", 0) >= 3)
        if refuse in ("media", "both") and restoring:
            raise RuntimeError("media refused")
        if color_scheme is not None:
            self.scheme = color_scheme
            self.schemes.append(color_scheme)

    def evaluate(self, expression: str, *args: object) -> object:
        if "prefers-color-scheme: dark" in expression:
            return self.scheme == "dark"
        if "typeof window.axe" in expression:
            return True
        if "axe.run" in expression:
            self.runs = getattr(self, "runs", 0) + 1
            if self.runs == getattr(self, "fail_on", None):
                raise RuntimeError("axe failed in pass %d" % self.runs)
            return {"violations": []}
        return None


def a11y_cases() -> int:
    """Run.a11y, taken out of e2e.py's syntax tree: its passes run at their own sizes and schemes,
    and afterwards the page is back at the step's own (tsk-7eq8y3gymek2)."""
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    run = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Run")
    method = next(n for n in run.body if isinstance(n, ast.FunctionDef) and n.name == "a11y")
    consts = [n for n in tree.body if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id in ("PASSES", "AXE_TAGS") for t in n.targets)]
    namespace = {"Page": object}
    exec(compile(ast.Module(body=consts + [method], type_ignores=[]), str(SOURCE), "exec"), namespace)
    a11y = namespace["a11y"]

    class Self:
        axe = "/* axe */"
        a11y_findings: list = []

    cases = []
    for width, height, scheme in ((390, 844, "dark"), (360, 780, "light"), (1280, 900, "light")):
        page = FakePage(width, height, scheme)
        with contextlib.redirect_stdout(io.StringIO()):
            a11y(Self(), page, "a view")
        passes = page.sizes[:3] == [(1280, 900), (390, 844), (1280, 900)] and page.schemes[:3] == ["light", "light", "dark"]
        back = page.viewport_size == {"width": width, "height": height} and page.scheme == scheme
        cases.append((f"a11y: the passes run, then the page is back at {width}x{height} {scheme}",
                      passes and back, (page.sizes, page.schemes)))
    # A pass that fails (axe throwing) still leaves the page as the step had it, and the error goes on (#1614 review).
    for fail_on in (1, 2, 3):
        page = FakePage(360, 780, "dark")
        page.fail_on = fail_on
        raised = None
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                a11y(Self(), page, "a view")
        except RuntimeError as err:
            raised = str(err)
        back = page.viewport_size == {"width": 360, "height": 780} and page.scheme == "dark"
        cases.append((f"a11y: axe failing in pass {fail_on} goes on as an error, the page back at 360x780 dark",
                      raised == "axe failed in pass %d" % fail_on and back, (raised, page.viewport_size, page.scheme)))
    # A restore the browser refuses (#1614 review): the other one is still tried, a pass error stays the error
    # that goes on, and with no pass error the refusal itself is raised.
    # Each start scheme differs from the one the passes leave (light after pass 1, dark after pass 3), so a
    # refused scheme restore shows.
    for fail_on, start, refuse, want, viewport_back, scheme_back in (
        (1, "dark", "viewport", "axe failed in pass 1", False, True),
        (1, "dark", "media", "axe failed in pass 1", True, False),
        (None, "light", "viewport", "viewport refused", False, True),
        (None, "light", "media", "media refused", True, False),
    ):
        page = FakePage(360, 780, start)
        page.fail_on, page.refuse = fail_on, refuse
        raised = None
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                a11y(Self(), page, "a view")
        except RuntimeError as err:
            raised = str(err)
        got = (raised, page.viewport_size == {"width": 360, "height": 780}, page.scheme == start)
        what = f"axe failing in pass {fail_on}" if fail_on else "no axe failure"
        cases.append((f"a11y: {what}, the {refuse} restore refused: {want!r} goes on, the other restore still made",
                      got == (want, viewport_back, scheme_back), got))
    # Both restores refused with no pass error: the first refusal is raised, the second is printed (#1614 review).
    page = FakePage(360, 780, "light")
    page.refuse = "both"
    out = io.StringIO()
    raised = None
    try:
        with contextlib.redirect_stdout(out):
            a11y(Self(), page, "a view")
    except RuntimeError as err:
        raised = str(err)
    cases.append(("a11y: no axe failure, both restores refused: the first is raised, the second printed",
                  raised == "viewport refused" and "media refused" in out.getvalue(), (raised, out.getvalue())))
    failed = 0
    for name, ok, detail in cases:
        failed += not ok
        print(("ok   " if ok else "FAIL ") + name + ("" if ok else f": {detail}"))
    return failed


SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)


def _own_scope(node: ast.AST):
    """Every node of a function's own body, not those of a function or class defined in it,
    which is a scope of its own and checked as one."""
    for child in ast.iter_child_nodes(node):
        yield child
        if not isinstance(child, SCOPES):
            yield from _own_scope(child)


def _called(node: ast.AST, name: str) -> bool:
    return isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == name


def catcher_functions(source: str) -> set[str]:
    """The functions of `source` that make a MailCatcher in their own scope: what
    `catcher_rounds` inspects, so a test can see it still finds the rounds it should."""
    return {
        node.name for node in ast.walk(ast.parse(source))
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name != "free_port"
        and any(_called(n, "MailCatcher") for n in _own_scope(node))
    }


def catcher_rounds(source: str) -> list[str]:
    """What is wrong with the port order of each function of e2e.py that starts a MailCatcher:
    every `free_port(` in that function must come after its last `MailCatcher(`, and must
    avoid the `.port` of every catcher, as `avoid=` or its first argument, directly or
    through a name the function assigned it to. Then the OS cannot hand a catcher the hub's
    port (tsk-vfdn98vwa0ym). A catcher bound to no name cannot be avoided and is a fault too.
    A catcher belongs to the function whose own scope makes it; a pick belongs to the
    innermost function around it that makes a catcher, so one in a nested def, lambda or
    default argument still counts for the round. One message per fault, naming the function
    and line. A helper at module level that picks or makes a catcher for a round is not
    followed (web/context/stack.md 65a9e67e, Known limits)."""
    faults = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) or node.name == "free_port":
            continue
        own = list(_own_scope(node))
        made = [n for n in own if _called(n, "MailCatcher")]
        if not made:
            continue
        names: dict[str, int] = {}  # a catcher's variable -> line of its MailCatcher()
        bound = set()
        for n in own:
            value = getattr(n, "value", None)
            if isinstance(n, ast.Assign) and _called(value, "MailCatcher"):
                targets = n.targets
            elif isinstance(n, ast.AnnAssign) and _called(value, "MailCatcher"):
                targets = [n.target]
            elif isinstance(n, ast.withitem) and _called(n.context_expr, "MailCatcher"):
                value, targets = n.context_expr, [n.optional_vars] if n.optional_vars else []
            else:
                continue
            for target in targets:
                if isinstance(target, ast.Name):
                    names[target.id] = value.lineno
                    bound.add(id(value))
        for call in made:
            if id(call) not in bound:
                faults.append(f"{node.name} (line {call.lineno}): a MailCatcher bound to no name, so no port can avoid it")
        last = max(call.lineno for call in made)
        assigned = {
            t.id: n.value for n in own if isinstance(n, ast.Assign) for t in n.targets if isinstance(t, ast.Name)
        }
        # A pick inside a nested def, lambda or default argument is still this round's pick
        # (review A2197), unless that nested function makes a catcher of its own: then it is
        # checked there, once. A harmless helper defined above the catcher is a loud fault,
        # which the strict ruling accepts over a silent gap.
        theirs = {
            id(x)
            for inner in ast.walk(node)
            if inner is not node and isinstance(inner, (ast.FunctionDef, ast.AsyncFunctionDef))
            and any(_called(n, "MailCatcher") for n in _own_scope(inner))
            for x in ast.walk(inner)
        }
        picks = [n for n in ast.walk(node) if _called(n, "free_port") and id(n) not in theirs]
        for call in sorted(picks, key=lambda c: (c.lineno, c.col_offset)):
            where = f"{node.name} (line {call.lineno})"
            if call.lineno < last:
                faults.append(f"{where}: free_port() before the MailCatcher of line {last}")
                continue
            avoid = next((k.value for k in call.keywords if k.arg == "avoid"), call.args[0] if call.args else None)
            if isinstance(avoid, ast.Name) and avoid.id in assigned:
                avoid = assigned[avoid.id]
            named = {
                n.value.id for n in ast.walk(avoid)
                if isinstance(n, ast.Attribute) and n.attr == "port" and isinstance(n.value, ast.Name)
            } if avoid is not None else set()
            missing = sorted(set(names) - named)
            if missing:
                faults.append(f"{where}: free_port() does not avoid the port of {missing}")
    return faults


class _Ports:
    """A stand-in for the socket module whose bind(("127.0.0.1", 0)) hands back the given
    ports in turn, as the OS could."""

    def __init__(self, ports: list[int]):
        self.ports = list(ports)

    def socket(self):
        outer = self

        class One:
            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

            def bind(self, _address):
                self.port = outer.ports.pop(0)

            def getsockname(self):
                return ("127.0.0.1", self.port)

        return One()


def port_cases(ns: dict) -> int:
    """tsk-vfdn98vwa0ym: a MailCatcher on the port free_port gave the hub answers the hub's
    health check (the CI failure of job 137502570723); free_port(avoid=) never returns the
    catcher's port; a listening catcher's port is never free; every round of e2e.py makes its
    catcher before it picks the hub's port, and avoids the catcher's."""
    cases = []
    # The old order, forced: free_port picks P and closes it, then a catcher binds P, as the OS
    # could do for a catcher on port 0. The hub's health check then reaches the catcher.
    taken = ns["free_port"]()
    catcher = ns["MailCatcher"](port=taken)
    # The client hangs up on the SMTP greeting, so the catcher's next write breaks its pipe:
    # expected here, and not worth a traceback on the output.
    catcher.server.handle_error = lambda *_: None
    try:
        try:
            # Straight to the loopback port: a proxy from the environment (HTTP_PROXY) must not
            # answer in its place.
            direct = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            direct.open(f"http://127.0.0.1:{taken}/api/v1/health", timeout=2)
            seen = "answered as HTTP"
        except http.client.BadStatusLine as error:
            seen = str(error)
        cases.append(("the old order: a catcher on the hub's port answers its health check",
                      "220 e2e catcher" in seen, seen))
    finally:
        catcher.server.shutdown()
        catcher.server.server_close()
    # The new order: the catcher listens first.
    catcher = ns["MailCatcher"]()
    try:
        cases.append(("a listening catcher's port is not free", ns["port_taken"](catcher.port), catcher.port))
        real = ns["socket"]
        try:
            other = catcher.port + 1 if catcher.port < 65535 else catcher.port - 1
            ns["socket"] = _Ports([catcher.port, other])
            got = ns["free_port"](avoid={catcher.port})
            cases.append(("free_port asks again when the OS hands back a port it avoids", got == other, got))
            ns["socket"] = _Ports([catcher.port])
            cases.append(("free_port without avoid takes what the OS gives",
                          ns["free_port"]() == catcher.port, catcher.port))
        finally:
            ns["socket"] = real
        picked = {ns["free_port"](avoid={catcher.port}) for _ in range(50)}
        cases.append(("50 real picks never give the catcher's port", catcher.port not in picked, catcher.port))
    finally:
        catcher.server.shutdown()
        catcher.server.server_close()
    # The guard on e2e.py itself, and that it sees the old order.
    source = SOURCE.read_text(encoding="utf-8")
    faults = catcher_rounds(source)
    cases.append(("every round of e2e.py makes its catcher first and avoids its port", not faults, faults))
    # And that it inspects the rounds it should: a refactor that hid the catchers from it
    # would otherwise pass with nothing checked (review A2196).
    rounds = {"second_hub_round", "mail_factor_round", "password_reset_round"}
    seen = catcher_functions(source)
    cases.append(("the guard inspects the three rounds that make a catcher", rounds <= seen, sorted(seen)))
    old = """
def mail_round(run):
    port = free_port()
    catcher = MailCatcher()

def unguarded_round(run):
    mailer = MailCatcher()
    port = free_port()
"""
    found = catcher_rounds(old)
    cases.append((
        "the guard names each round with the old order or no avoid",
        len(found) == 2 and found[0].startswith("mail_round") and found[1].startswith("unguarded_round"),
        found,
    ))
    # The forms review A2195 found the first guard to miss or to refuse wrongly.
    for name, sample, want in [
        ("an annotated catcher after its port", "def r():\n    port = free_port()\n    c: MailCatcher = MailCatcher()\n", 1),
        ("a catcher made in a with", "def r():\n    with MailCatcher() as c:\n        port = free_port()\n", 1),
        ("a catcher made in a with, its port avoided",
         "def r():\n    with MailCatcher() as c:\n        port = free_port(avoid={c.port})\n", 0),
        ("a second catcher after the port",
         "def r():\n    a = MailCatcher()\n    port = free_port(avoid={a.port})\n    b = MailCatcher()\n", 1),
        ("two catchers, one avoided",
         "def r():\n    a = MailCatcher()\n    b = MailCatcher()\n    port = free_port(avoid={a.port})\n", 1),
        ("two catchers, both avoided",
         "def r():\n    a = MailCatcher()\n    b = MailCatcher()\n    port = free_port(avoid={a.port, b.port})\n", 0),
        ("a catcher bound to no name", "def r():\n    use(MailCatcher())\n    port = free_port()\n", 1),
        ("a catcher on an attribute", "def r(run):\n    run.catcher = MailCatcher()\n    port = free_port()\n", 1),
        ("a catcher returned by a helper", "def make():\n    return MailCatcher()\n", 1),
        ("a pick in a nested def before the catcher is the round's (A2197)",
         "def r():\n    def pick():\n        return free_port()\n    port = pick()\n    c = MailCatcher()\n", 1),
        ("a pick in a lambda before the catcher is the round's",
         "def r():\n    pick = lambda: free_port()\n    port = pick()\n    c = MailCatcher()\n", 1),
        ("a pick in a default argument before the catcher is the round's",
         "def r():\n    def go(p=free_port()):\n        return p\n    c = MailCatcher()\n", 1),
        ("a nested pick after the catcher without avoid is the round's",
         "def r():\n    c = MailCatcher()\n    def pick():\n        return free_port()\n    port = pick()\n", 1),
        ("a nested function with its own catcher is checked there, once",
         "def r():\n    def inner():\n        port = free_port()\n        c = MailCatcher()\n    d = MailCatcher()\n", 1),
        ("avoid passed by position", "def r():\n    c = MailCatcher()\n    port = free_port({c.port})\n", 0),
        ("avoid through a name assigned in the round",
         "def r():\n    c = MailCatcher()\n    skip = {c.port}\n    port = free_port(avoid=skip)\n", 0),
    ]:
        got = catcher_rounds(sample)
        cases.append((f"the guard: {name}", len(got) == want, got))
    failed = 0
    for name, ok, detail in cases:
        failed += not ok
        print(("ok   " if ok else "FAIL ") + name + ("" if ok else f": {detail}"))
    return failed


def main() -> int:
    ns = load()
    cases = [
        ("no answer is no problem", [], 0),
        ("every answer of 400 or more stays a problem, the chat list's 404 too",
         ["GET /api/v1/me/conversations?observed=true&limit=200 answered 404",
          "GET /api/v1/me/notifications?limit=0 answered 404"], 2),
    ]
    failed = 0
    for name, said, want in cases:
        got = problems(ns, said)
        ok = len(got) == want
        failed += not ok
        print(("ok   " if ok else "FAIL ") + name + ("" if ok else f": {got}"))
    failed += trace_cases(ns)
    failed += boot_head_cases(ns)
    failed += environment_cases(ns)
    failed += lock_cases(ns)
    failed += a11y_cases()
    failed += port_cases(ns)
    print("all ok" if not failed else f"{failed} failure(s)")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
