"""The web job runs whenever a file that make check reads changes.

tools/check.py reads some files outside web/ (the hub's words, docs/api.md, the landing page's
script). The `changes` job of .github/workflows/ci.yml starts the web job only for the paths its
`web:` patterns match; a read path no pattern matches lets a pull request change that file with
the web job skipped, and main goes red after the merge (tsk-fffx19yteh4x, context/process.md).
This test collects every path check.py builds from the repository root and fails unless a `web:`
pattern matches it. Python standard library only: python3 web/tools/test_ci_paths.py
"""
import fnmatch
import os
import re
import sys

WEB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = os.path.dirname(WEB)
CHECK = os.path.join(WEB, "tools", "check.py")
CI = os.path.join(REPO, ".github", "workflows", "ci.yml")

# os.path.join(os.path.dirname(ROOT), "docs", "api.md"): the parts are string literals.
OUTSIDE = re.compile(r"os\.path\.join\(\s*os\.path\.dirname\(ROOT\)\s*((?:,\s*\"[^\"]+\"\s*)+)\)")
PART = re.compile(r"\"([^\"]+)\"")
# One arm of the changes job's case: `web:web/*|web:docs/api.md) hit=true ;;`.
ARM = re.compile(r"^\s*((?:[a-z0-9]+:[^|)\s]+\|?)+)\)\s*hit=true\s*;;\s*$")


def outside_reads(source):
    """Every repository path, relative to the root, that check.py builds from ROOT's parent."""
    found = set()
    for match in OUTSIDE.finditer(source):
        found.add("/".join(PART.findall(match.group(1))))
    return sorted(found)


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
        reads = outside_reads(handle.read())
    with open(CI, encoding="utf-8") as handle:
        patterns = web_patterns(handle.read())
    failures = 0
    if not reads:
        print("FAIL check.py builds no path outside web/: the pattern above no longer finds them")
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
