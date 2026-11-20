"""tools/shell_budget.py on small stand-in dashboards: what it counts as loaded by the shell, and
that it fails once the files, their bytes or their gzipped bytes are over the budget.
Python standard library only: python3 web/tools/test_shell_budget.py
"""

import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "shell_budget", Path(__file__).with_name("shell_budget.py")
)
shell_budget = importlib.util.module_from_spec(spec)
spec.loader.exec_module(shell_budget)

failures = 0


def expect(ok, what):
    global failures
    if not ok:
        failures += 1
    print(("ok   " if ok else "FAIL ") + what)


SHELL = """<!doctype html><html><head>
<link rel="stylesheet" href="css/app.css">
<link rel="icon" href="brand/favicon.svg">
<script src="js/a.js"></script>
<script src="js/b.js?v=0123456789abcdef" defer></script>
<script>inline();</script>
</head><body></body></html>"""


def dashboard(root, files, budget, shell=SHELL):
    for name, text in {"index.html": shell, **files}.items():
        path = os.path.join(root, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
    os.makedirs(os.path.join(root, "tools"), exist_ok=True)
    with open(os.path.join(root, "tools", "shell-budget.json"), "w", encoding="utf-8") as f:
        json.dump(budget, f)
    return shell_budget.check(root, os.path.join(root, "tools", "shell-budget.json"))


FILES = {
    "css/app.css": '@import url("parts/b.css");\nbody{}\n',
    "css/parts/b.css": "p{}\n",
    "js/a.js": "a();\n",
    "js/b.js": "b();\n",
    "brand/favicon.svg": "<svg/>",
}
size = sum(len(text.encode()) for name, text in FILES.items() if not name.endswith(".svg"))

with tempfile.TemporaryDirectory() as root:
    problems, measured, _ = dashboard(root, FILES, {"files": 4, "bytes": size, "gzip_bytes": 10**6})
    expect(problems == [], "within the budget: no problem " + repr(problems))
    expect(measured["files"] == 4, "the stylesheet, its @import and both scripts; no icon, no inline script " + repr(measured))
    expect(measured["bytes"] == size, "bytes as stored, a ?v= query dropped " + repr(measured))

with tempfile.TemporaryDirectory() as root:
    problems, _, _ = dashboard(root, FILES, {"files": 3, "bytes": size, "gzip_bytes": 10**6})
    expect(any(p.startswith("files: 4 over the budget of 3") for p in problems), "one file over the count fails " + repr(problems))

with tempfile.TemporaryDirectory() as root:
    problems, _, _ = dashboard(root, FILES, {"files": 4, "bytes": size - 1, "gzip_bytes": 10**6})
    expect(any(p.startswith("bytes:") for p in problems), "one byte over fails " + repr(problems))

with tempfile.TemporaryDirectory() as root:
    problems, measured, _ = dashboard(root, FILES, {"files": 4, "bytes": size, "gzip_bytes": 1})
    expect(any(p.startswith("gzip_bytes:") for p in problems), "over the gzipped budget fails " + repr(problems))

with tempfile.TemporaryDirectory() as root:
    shell = SHELL.replace("</head>", '<script src="https://cdn.example/x.js"></script><script src="js/gone.js"></script></head>')
    problems, _, _ = dashboard(root, FILES, {"files": 9, "bytes": 10**6, "gzip_bytes": 10**6}, shell)
    expect(any("cdn.example" in p for p in problems), "a file from elsewhere cannot be measured, and fails " + repr(problems))
    expect(any("js/gone.js" in p and "missing" in p for p in problems), "a file the shell names that is missing fails " + repr(problems))

with tempfile.TemporaryDirectory() as root:
    problems, _, _ = dashboard(root, FILES, {"files": 4, "bytes": "3 MB", "gzip_bytes": 10**6})
    expect(any("`bytes` is not a whole number" in p for p in problems), "a budget that is no number fails " + repr(problems))

with tempfile.TemporaryDirectory() as root:
    problems, _, _ = dashboard(root, FILES, {"files": True, "bytes": size, "gzip_bytes": 10**6})
    expect(any("`files` is not a whole number" in p for p in problems), "a budget of true is no number (JSON true is an int in Python) " + repr(problems))

with tempfile.TemporaryDirectory() as root:
    problems, _, _ = dashboard(root, FILES, {"files": 5, "bytes": size, "gzip_bytes": 10**6})
    expect(any(p.startswith("files: 4 under the budget of 5") for p in problems), "one file under the count fails: the budget is the count " + repr(problems))

print("%d failure(s)" % failures)
sys.exit(1 if failures else 0)
