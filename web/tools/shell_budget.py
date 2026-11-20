"""The script and style files the dashboard shell loads stay within a committed budget.

Reads web/index.html: every <script src> and <link rel="stylesheet" href>, and every @import of
a stylesheet it loads, followed. Counts the files, their bytes as stored, and their bytes
gzipped (level 9, what a compressed answer is near), and fails when one of the three is over
tools/shell-budget.json. Files a script loads later by a name it builds (another language's
catalog, the fixtures, Keep the Why's views) are not counted: the shell does not name them.

A pull request that needs more raises the number in shell-budget.json, so the raise is in its
diff and its review (context/performance.md, item 15; web/context/stack.md). Python standard
library only: python3 web/tools/shell_budget.py [--root DIR]
"""

import gzip
import json
import os
import re
import sys
from html.parser import HTMLParser

WEB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMPORT = re.compile(r"""@import\s+(?:url\(\s*)?["']?([^"')\s;]+)""")
KEYS = ("files", "bytes", "gzip_bytes")


class _Shell(HTMLParser):
    def __init__(self):
        super().__init__()
        self.found = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "script" and a.get("src"):
            self.found.append(a["src"])
        rel = (a.get("rel") or "").lower().split()
        if tag == "link" and "stylesheet" in rel and a.get("href"):
            self.found.append(a["href"])


def _local(ref, base, root):
    """The file `ref` names, relative to the file `base` it is named in; None for a URL
    elsewhere, which this budget cannot measure."""
    ref = ref.split("?", 1)[0].split("#", 1)[0]
    if re.match(r"^[a-z][a-z0-9+.-]*:|^//", ref, re.I):
        return None
    start = root if ref.startswith("/") else os.path.dirname(base)
    return os.path.normpath(os.path.join(start, ref.lstrip("/")))


def shell_files(root):
    """The files the shell at root/index.html loads, in order, each once; and the references
    that are no local file."""
    index = os.path.join(root, "index.html")
    parser = _Shell()
    with open(index, encoding="utf-8") as f:
        parser.feed(f.read())
    files, outside, todo = [], [], [(ref, index) for ref in parser.found]
    while todo:
        ref, base = todo.pop(0)
        path = _local(ref, base, root)
        if path is None:
            outside.append(ref)
            continue
        if path in files:
            continue
        files.append(path)
        if path.endswith(".css") and os.path.isfile(path):
            with open(path, encoding="utf-8") as f:
                todo.extend((found, path) for found in IMPORT.findall(f.read()))
    return files, outside


def measure(root):
    files, outside = shell_files(root)
    missing = [p for p in files if not os.path.isfile(p)]
    sizes, packed = 0, 0
    for path in files:
        if path in missing:
            continue
        with open(path, "rb") as f:
            data = f.read()
        sizes += len(data)
        packed += len(gzip.compress(data, 9, mtime=0))
    return {"files": len(files), "bytes": sizes, "gzip_bytes": packed}, outside, missing


def check(root, budget_path):
    """The problems, empty when the shell is within its budget; and the measured numbers."""
    with open(budget_path, encoding="utf-8") as f:
        budget = json.load(f)
    measured, outside, missing = measure(root)
    problems = [f"{ref}: not a file of the dashboard, so not measured" for ref in outside]
    problems += [f"{os.path.relpath(p, root)}: loaded by the shell, missing" for p in missing]
    for key in KEYS:
        value = budget.get(key)
        if not isinstance(value, int) or isinstance(value, bool):
            problems.append(f"{os.path.basename(budget_path)}: `{key}` is not a whole number")
        elif measured[key] > budget[key]:
            problems.append(
                f"{key}: {measured[key]} over the budget of {budget[key]}; raise it in "
                f"{os.path.relpath(budget_path, root)} if the pull request means to"
            )
    return problems, measured, budget


def main(argv):
    root = WEB
    if "--root" in argv:
        root = argv[argv.index("--root") + 1]
    problems, measured, budget = check(root, os.path.join(root, "tools", "shell-budget.json"))
    for key in KEYS:
        print(f"shell {key}: {measured[key]} of {budget.get(key)}")
    for problem in problems:
        print(f"shell budget: {problem}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
