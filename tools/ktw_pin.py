#!/usr/bin/env python3
"""Every pinned copy of the Keep the Why skill names the version this repository's context is on.

The context schema in `.keep-the-why` (`context-schema: X`) is the release the context was
migrated to. The skill's install instructions (`keep-the-why/tree/vX/...`), the Git fallback
(`--branch vX`) and the linter action (`# lint-vX.N`) must name that release, and every `npx
skills@V` must name the installer version that `hub/src/maity_hub/ktw_skill.py` pins. Whoever
migrates the context bumps every copy in the same pull request; a moving `latest` fails.

    python3 tools/ktw_pin.py          # from the repository root; exit 1 with one line per finding

Standard library only.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# Where the skill's install instructions and its linter are written down.
FILES = (
    "AGENTS.md",
    "docs/api.md",
    "hub/README.md",
    "hub/src/maity_hub/config.py",
    "hub/src/maity_hub/ktw_skill.py",
    "hub/tests/test_keep_the_why_policy.py",
    ".github/workflows/ktw-lint.yml",
)
INSTALLER_SOURCE = "hub/src/maity_hub/ktw_skill.py"

TREE = re.compile(r"keep-the-why/tree/([^/\s\"'`]+)/")
BRANCH = re.compile(r"--branch (\S+) https://github\.com/oliver-zehentleitner/keep-the-why\b")
NPX = re.compile(r"npx skills(@[^\s\"'`]*)?\s")
INSTALLER = re.compile(r'^SKILLS_INSTALLER = "skills@([^"]+)"$', re.MULTILINE)
LINT_ACTION = re.compile(r"uses: oliver-zehentleitner/keep-the-why@(\S+)(?:\s*#\s*(\S+))?")
SCHEMA = re.compile(r"^- context-schema:\s*(\S+)\s*$", re.MULTILINE)


def schema(root: Path) -> str:
    found = SCHEMA.search((root / ".keep-the-why").read_text(encoding="utf-8"))
    if not found:
        raise SystemExit("ktw_pin: .keep-the-why names no context-schema")
    return found.group(1)


def check(root: Path) -> list[str]:
    version = schema(root)
    release = f"v{version}"
    pinned = INSTALLER.search((root / INSTALLER_SOURCE).read_text(encoding="utf-8"))
    problems: list[str] = []
    if not pinned:
        problems.append(f'{INSTALLER_SOURCE}: no SKILLS_INSTALLER = "skills@<version>"')
    installer = pinned.group(1) if pinned else None
    for name in FILES:
        path = root / name
        if not path.exists():
            problems.append(f"{name}: missing (named in tools/ktw_pin.py)")
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            where = f"{name}:{number}"
            for ref in TREE.findall(line):
                if ref != release:
                    problems.append(
                        f"{where}: the skill's tree is {ref!r}, context-schema is {version}"
                    )
            for ref in BRANCH.findall(line):
                if ref != release:
                    problems.append(
                        f"{where}: the Git fallback's branch is {ref!r}, context-schema is {version}"
                    )
            for match in NPX.finditer(line):
                at = match.group(1)
                if not at or at == "@":
                    problems.append(f"{where}: `npx skills` without a version")
                elif installer and at[1:] != installer:
                    problems.append(
                        f"{where}: `npx skills{at}`, {INSTALLER_SOURCE} pins skills@{installer}"
                    )
            for ref, tag in LINT_ACTION.findall(line):
                if not re.fullmatch(r"[0-9a-f]{40}", ref):
                    problems.append(f"{where}: the linter action is {ref!r}, not a commit SHA")
                if not tag.startswith(f"lint-v{version}."):
                    problems.append(
                        f"{where}: the linter action's tag is {tag or 'unnamed'}, context-schema is {version}"
                    )
    return problems


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    problems = check(root)
    for problem in problems:
        print(problem, file=sys.stderr)
    if problems:
        return 1
    print(f"ktw_pin: every copy names v{schema(root)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
