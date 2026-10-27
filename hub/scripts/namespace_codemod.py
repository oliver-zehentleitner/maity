"""The mechanical half of the project namespace (docs/api.md §6.25), as a script.

Rewrites project route paths from `/projects/{slug}` to `/projects/{owner}/{slug}`, gives every
route module's router the `ProjectRoute` class that hands a route the full name as `slug`, and
moves the tests' project paths into the namespace of the human that creates the project in
the test helpers (`maintainer`). It is idempotent: a second run changes nothing, so a rebase
re-runs it instead of merging hundreds of path literals by hand.

    python scripts/namespace_codemod.py            # rewrite in place
    python scripts/namespace_codemod.py --check    # exit 1 if anything is left to rewrite
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROUTES = ROOT / "src" / "maity_hub" / "routes"
TESTS = ROOT / "tests"
# The handle `tests/flow.py` gives the human that creates a project, and the slugs tests use.
OWNER = "maintainer"
# The namespace's own tests send the old paths on purpose.
EXEMPT = frozenset({"test_namespace.py"})
TEST_SLUGS = ("maity", "widget", "beta", "other", "alpha", "closed", "elsewhere")

ROUTE_PATH = re.compile(r"/projects/\{slug\}")
FSTRING_PATH = re.compile(r"/projects/\{\{slug\}\}")
PLAIN_ROUTER = re.compile(r"\bAPIRouter\(\)")
IMPORT = "from maity_hub.namespace import ProjectRoute\n"
TEST_BADGE = re.compile(r"/badge/(" + "|".join(TEST_SLUGS) + r"|p-\{preset\})\.svg")
TEST_SWARM = re.compile(r"/api/v1/swarm/\{slug\}")
TEST_FSTRING = re.compile(r"/projects/\{slug\}")
TEST_PATH = re.compile(r"/projects/(" + "|".join(TEST_SLUGS) + r")(?=[/\"'?#]|$)")


def routes(text: str) -> str:
    text = ROUTE_PATH.sub("/projects/{owner}/{slug}", text)
    text = FSTRING_PATH.sub("/projects/{{owner}}/{{slug}}", text)
    if PLAIN_ROUTER.search(text) and "/projects/{owner}/{slug}" in text:
        text = PLAIN_ROUTER.sub("APIRouter(route_class=ProjectRoute)", text)
        if IMPORT not in text:
            text = _add_import(text)
    return text


def _add_import(text: str) -> str:
    """After the module's last top-level import statement, multi-line ones included."""
    tree = ast.parse(text)
    last = max(
        node.end_lineno or node.lineno
        for node in tree.body
        if isinstance(node, ast.Import | ast.ImportFrom)
    )
    lines = text.splitlines(keepends=True)
    lines.insert(last, IMPORT)
    return "".join(lines)


def tests(text: str) -> str:
    text = TEST_PATH.sub(lambda m: f"/projects/{OWNER}/{m[1]}", text)
    text = TEST_FSTRING.sub(f"/projects/{OWNER}/{{slug}}", text)
    text = TEST_BADGE.sub(lambda m: f"/badge/{OWNER}/{m[1]}.svg", text)
    return TEST_SWARM.sub(f"/api/v1/swarm/{OWNER}/{{slug}}", text)


def main(argv: list[str]) -> int:
    check = "--check" in argv
    changed = []
    for folder, rewrite in ((ROUTES, routes), (TESTS, tests)):
        for path in sorted(folder.rglob("*.py")):
            if path.name in EXEMPT:
                continue
            old = path.read_text(encoding="utf-8")
            new = rewrite(old)
            if new != old:
                changed.append(path.relative_to(ROOT))
                if not check:
                    path.write_text(new, encoding="utf-8")
    for path in changed:
        print(path)
    return 1 if check and changed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
