"""The e2e harness's own judgement of answers, without a browser or a hub.

e2e.py imports Playwright at the top; this reads only the parts it tests out of
the file's syntax tree (PENDING_UPLOADS, off_problem, no_problems) and runs them
on stand-in answers. Python standard library only: python3 web/tools/test_e2e_harness.py
"""

import ast
import contextlib
import io
import json
import re
import sys
import tempfile
from pathlib import Path

SOURCE = Path(__file__).with_name("e2e.py")
WANTED = {
    "PENDING_UPLOADS", "off_problem", "no_problems",
    "TRACE_BODY", "TRACE_KEYS", "TRACE_SECRET_AFTER", "TRACE_WORD", "TRACE_VALUE",
    "trace_path", "trace_data", "trace_scalar", "trace_line", "report_failure",
}


def load() -> dict:
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    nodes = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in WANTED:
            nodes.append(node)
        elif isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id in WANTED for t in node.targets):
            nodes.append(node)
    found = {n.name if isinstance(n, ast.FunctionDef) else n.targets[0].id for n in nodes}
    if found != WANTED:
        sys.exit(f"e2e.py lacks {sorted(WANTED - found)}")
    namespace = {"re": re, "json": json, "sys": sys, "Path": Path, "Run": object}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(SOURCE), "exec"), namespace)
    return namespace


BASE = "http://127.0.0.1:9"
PENDING = "/api/v1/projects/owner/e2e-alpha/attachments?status=pending&uploaded_by=hum-1&limit=200"


class Request:
    def __init__(self, method: str):
        self.method = method


class Answer:
    """A stand-in for Playwright's Response: method, url, status and a JSON body."""

    def __init__(self, status: int, code: str | None, method: str = "GET", path: str = PENDING):
        self.request = Request(method)
        self.url = BASE + path
        self.status = status
        self.code = code

    def json(self):
        if self.code is None:
            raise ValueError("not JSON")
        return {"error": {"code": self.code, "message": "…", "details": {}}}


class FakeRun:
    def __init__(self, answers):
        self.base = BASE
        self.problems = []
        self.off_answers = list(answers)


def problems(ns: dict, answers) -> list[str]:
    run = FakeRun(answers)
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
SECRETS = ["JOINTOKENabc123", "PAIRTOKENxyz789", "QUERYTOKENq1", "CODE-AAAA-BBBB", "CREDmty1.rcrd-SECRET", "NESTEDsecret42", "PLAINTEXTsecret"]


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
    check("a token path is masked, the query is dropped", lines[0].startswith("GET /api/v1/join/… 200") and "?" not in lines[2].split(" ")[1], lines[:3])
    check("the runner's state is kept", '"credential_state":"active"' in lines[2] and '"presence":"offline"' in lines[2] and "rnr-abc123def" in lines[2], lines[2])
    check("a nested secret is dropped, a nested allowed key is kept", '"state":"ok"' in lines[2] and "NESTED" not in lines[2], lines[2])
    check("an error keeps its code, not its message", '"code":"forbidden"' in lines[4] and "message" not in lines[4], lines[4])
    check("an enrollment keeps no code", '"code"' not in lines[3], lines[3])
    check("a body that is not JSON, or gone, is not shown", lines[1].endswith("(body not shown)") and lines[5].endswith("(body not shown)") and lines[6].endswith("(body not shown)"), lines)
    return failed


def main() -> int:
    ns = load()
    off = lambda: Answer(409, "attachments_not_configured")  # noqa: E731
    other = lambda: Answer(409, "other_conflict")  # noqa: E731
    cases = [
        ("one answer of attachments off is no problem", [off()], 0),
        ("off, then another conflict: the other one is a problem", [off(), other()], 1),
        ("another conflict, then off: the other one is a problem", [other(), off()], 1),
        ("a 409 without a JSON body is a problem", [Answer(409, None)], 1),
        ("the code on another method is a problem", [Answer(409, "attachments_not_configured", method="POST")], 1),
        ("the code on another path is a problem",
         [Answer(409, "attachments_not_configured", path="/api/v1/projects/owner/e2e-alpha/attachments?name=a.png")], 1),
        ("the code with another status is a problem", [Answer(500, "attachments_not_configured")], 1),
    ]
    failed = 0
    for name, answers, want in cases:
        got = problems(ns, answers)
        ok = len(got) == want
        failed += not ok
        print(("ok   " if ok else "FAIL ") + name + ("" if ok else f": {got}"))
    # The problem says which answer it was, with its code.
    said = problems(ns, [off(), other()])
    if said != [f"GET {PENDING} answered 409 (other_conflict)"]:
        failed += 1
        print(f"FAIL the problem names the answer and its code: {said}")
    else:
        print("ok   the problem names the answer and its code")
    failed += trace_cases(ns)
    print("all ok" if not failed else f"{failed} failure(s)")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
