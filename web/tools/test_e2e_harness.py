"""The e2e harness's own judgement of answers, without a browser or a hub.

e2e.py imports Playwright at the top; this reads only the parts it tests out of
the file's syntax tree (PENDING_UPLOADS, off_problem, no_problems) and runs them
on stand-in answers. Python standard library only: python3 web/tools/test_e2e_harness.py
"""

import ast
import re
import sys
from pathlib import Path

SOURCE = Path(__file__).with_name("e2e.py")
WANTED = {"PENDING_UPLOADS", "off_problem", "no_problems"}


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
    namespace = {"re": re, "Run": object}
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
    print("all ok" if not failed else f"{failed} failure(s)")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
