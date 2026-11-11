"""The web job runs whenever a file that make check reads changes.

tools/check.py reads some files outside web/ (the hub's words, docs/api.md, the landing page's
script). The `changes` job of .github/workflows/ci.yml starts the web job only for the paths its
`web:` patterns match; a read path no pattern matches lets a pull request change that file with
the web job skipped, and main goes red after the merge (tsk-fffx19yteh4x, context/process.md).
This test collects every path check.py builds from the repository root and fails unless a `web:`
pattern matches it. Python standard library only: python3 web/tools/test_ci_paths.py
"""
import ast
import fnmatch
import os
import re
import sys

WEB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = os.path.dirname(WEB)
CHECK = os.path.join(WEB, "tools", "check.py")
CI = os.path.join(REPO, ".github", "workflows", "ci.yml")

# One arm of the changes job's case: `web:web/*|web:docs/api.md) hit=true ;;`.
ARM = re.compile(r"^\s*((?:[a-z0-9]+:[^|)\s]+\|?)+)\)\s*hit=true\s*;;\s*$")


def is_call(node, *names):
    """node is a call of the dotted name names (os.path.join is "os", "path", "join")."""
    if not isinstance(node, ast.Call):
        return False
    func, parts = node.func, []
    while isinstance(func, ast.Attribute):
        parts.append(func.attr)
        func = func.value
    if isinstance(func, ast.Name):
        parts.append(func.id)
    return tuple(reversed(parts)) == names


def outside_reads(source):
    """Every repository path, relative to the root, that check.py builds from ROOT's parent, and
    every use of os.path.dirname(ROOT) this cannot read as such a path. Read from the syntax tree,
    so the quotes, a trailing comma or a line break do not matter. A recognised path is
    os.path.join(os.path.dirname(ROOT), "a", "b") with string literals only; anything else that
    starts from ROOT's parent (a variable part, the parent kept in a name) is returned as
    unreadable, with its line, for the test to refuse rather than skip."""
    tree = ast.parse(source)
    parent = [n for n in ast.walk(tree) if is_call(n, "os", "path", "dirname")
              and len(n.args) == 1 and isinstance(n.args[0], ast.Name) and n.args[0].id == "ROOT"]
    found, used = set(), set()
    for node in ast.walk(tree):
        if not is_call(node, "os", "path", "join") or not node.args or node.args[0] not in parent:
            continue
        rest = node.args[1:]
        if rest and not node.keywords and all(isinstance(a, ast.Constant) and isinstance(a.value, str) for a in rest):
            found.add("/".join(a.value for a in rest))
            used.add(id(node.args[0]))
    unreadable = sorted(n.lineno for n in parent if id(n) not in used)
    return sorted(found), unreadable


def web_patterns(workflow):
    """The `web:` patterns of the changes job's case, and the `*:` ones that match every part."""
    patterns = []
    for line in workflow.splitlines():
        arm = ARM.match(line)
        if not arm:
            continue
        for alternative in arm.group(1).split("|"):
            part, _, pattern = alternative.partition(":")
            if part in ("web", "*"):
                patterns.append(pattern)
    return patterns


def covered(path, patterns):
    """A shell case pattern's `*` matches `/` too, as fnmatchcase's does. A directory is read
    file by file, so it is tested with a file inside it."""
    probe = path + "/x" if os.path.isdir(os.path.join(REPO, path)) else path
    return any(fnmatch.fnmatchcase(probe, pattern) for pattern in patterns)


def main():
    with open(CHECK, encoding="utf-8") as handle:
        reads, unreadable = outside_reads(handle.read())
    with open(CI, encoding="utf-8") as handle:
        patterns = web_patterns(handle.read())
    failures = 0
    if not reads:
        print("FAIL check.py builds no path outside web/: outside_reads no longer finds them")
        failures += 1
    for line in unreadable:
        print("FAIL tools/check.py:%d starts from os.path.dirname(ROOT) but is not os.path.join(os.path.dirname(ROOT), "
              "\"a\", \"b\") with string literals: write it so, or this test cannot hold ci.yml to it" % line)
        failures += 1
    if not any(p.startswith("web/") for p in patterns):
        print("FAIL ci.yml has no web:web/* arm: the changes job's case no longer parses")
        failures += 1
    for path in reads:
        if covered(path, patterns):
            print("ok   %s starts the web job" % path)
        else:
            print("FAIL %s is read by tools/check.py, but no web: pattern of ci.yml's changes job matches it" % path)
            failures += 1
    # The reading itself, on stand-in sources: any spelling of the join is found, anything else
    # that starts from ROOT's parent is refused with its line.
    for label, source, want in (
        ("double quotes", 'os.path.join(os.path.dirname(ROOT), "docs", "x.md")\n', (["docs/x.md"], [])),
        ("single quotes", "os.path.join(os.path.dirname(ROOT), 'docs', 'x.md')\n", (["docs/x.md"], [])),
        ("mixed quotes", "os.path.join(os.path.dirname(ROOT), 'docs', \"x.md\")\n", (["docs/x.md"], [])),
        ("trailing comma", 'os.path.join(os.path.dirname(ROOT), "docs", "x.md",)\n', (["docs/x.md"], [])),
        ("over lines", 'os.path.join(\n    os.path.dirname(ROOT),\n    "docs",\n    "x.md",\n)\n', (["docs/x.md"], [])),
        ("a variable part", 'name = "x.md"\nos.path.join(os.path.dirname(ROOT), "docs", name)\n', ([], [2])),
        ("the parent in a name", 'up = os.path.dirname(ROOT)\nos.path.join(up, "docs", "x.md")\n', ([], [1])),
        ("the parent alone", 'os.path.join(os.path.dirname(ROOT))\n', ([], [1])),
        ("another root", 'os.path.join(os.path.dirname(HERE), "docs", "x.md")\n', ([], [])),
    ):
        got = outside_reads(source)
        if got != want:
            print("FAIL outside_reads, %s: %r, expected %r" % (label, got, want))
            failures += 1
    # The judgement itself, on stand-in input: a path outside every pattern is refused.
    for path, pats, want in (
        ("docs/api.md", ["web/*"], False),
        ("docs/api.md", ["web/*", "docs/api.md"], True),
        ("hub/src/maity_hub/landing_assets/landing.js", ["hub/src/maity_hub/landing_assets/*"], True),
        ("hub/words-meta", ["hub/words-meta/*"], True),
        ("hub/words-meta", ["hub/words/*"], False),
    ):
        got = covered(path, pats)
        if got != want:
            print("FAIL covered(%r, %r) is %r, expected %r" % (path, pats, got, want))
            failures += 1
    print("all ok" if not failures else "%d failure(s)" % failures)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
