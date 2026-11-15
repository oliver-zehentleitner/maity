#!/usr/bin/env python3
"""Checks that a hub release has its upgrade page, docs/upgrade/<version>.md.

Every hub release ships a page that tells an operator, without knowing the
code, what the upgrade changes and what they must do (docs/upgrade/README.md).
The page has five sections, as second-level headings in this order:

    ## What changes for users
    ## What the operator must do
    ## What happens by itself on upgrade
    ## What cannot be undone
    ## The way back

Each section holds text (a line such as "Nothing." counts).

`check` (ci, every pull request): the hub's version is the one in
hub/pyproject.toml. Once CHANGELOG.md has that version's section (the release
pull request folds it in), its page must exist and be complete; before that,
nothing is asked. `--version X` checks the page of X whatever CHANGELOG.md says;
tools/release_gate.py asks for the tagged version this way.
Standard library only.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SECTIONS = (
    "What changes for users",
    "What the operator must do",
    "What happens by itself on upgrade",
    "What cannot be undone",
    "The way back",
)
VERSION = re.compile(r'^version\s*=\s*"([^"]+)"\s*$', re.MULTILINE)


def hub_version(root: Path = ROOT) -> str:
    """The version in hub/pyproject.toml."""
    found = VERSION.search((root / "hub" / "pyproject.toml").read_text(encoding="utf-8"))
    if not found:
        raise ValueError("hub/pyproject.toml has no version line")
    return found.group(1)


def released(root: Path, version: str) -> bool:
    """Whether CHANGELOG.md has a section for this version."""
    text = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    return re.search(rf"^## \[{re.escape(version)}\]", text, re.MULTILINE) is not None


def problems(root: Path, version: str) -> list[str]:
    """What is wrong with docs/upgrade/<version>.md; empty when nothing is."""
    path = root / "docs" / "upgrade" / f"{version}.md"
    name = path.relative_to(root).as_posix()
    if not path.is_file():
        return [
            f"{name} is missing: every hub release has an upgrade page"
            " (docs/upgrade/README.md has the template)"
        ]
    headings: list[str] = []
    bodies: dict[str, list[str]] = {}
    fence = False
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("```"):
            # A fence line is no text of its own: an empty code block leaves a section empty.
            fence = not fence
            continue
        if not fence and line.startswith("## "):
            headings.append(line[3:].strip())
            bodies[headings[-1]] = []
        elif headings:
            bodies[headings[-1]].append(line)
    found = [h for h in headings if h in SECTIONS]
    out = []
    missing = [s for s in SECTIONS if s not in found]
    if missing:
        out.append(f"{name} lacks the section(s): " + "; ".join(f"## {s}" for s in missing))
    elif found != list(SECTIONS) or len(set(found)) != len(found):
        out.append(f"{name}: the sections must appear once each, in this order: " + "; ".join(SECTIONS))
    for section in SECTIONS:
        if section in bodies and not any(line.strip() for line in bodies[section]):
            out.append(f"{name}: '## {section}' is empty (write 'Nothing.' if nothing applies)")
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=["check"])
    parser.add_argument("--version", help="check this version's page, released or not")
    args = parser.parse_args(argv)
    version = args.version or hub_version(ROOT)
    if not args.version and not released(ROOT, version):
        print(f"hub {version} is not folded into CHANGELOG.md yet: no upgrade page asked")
        return 0
    found = problems(ROOT, version)
    for problem in found:
        print(f"::error::{problem}")
    if found:
        return 1
    print(f"docs/upgrade/{version}.md: complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
