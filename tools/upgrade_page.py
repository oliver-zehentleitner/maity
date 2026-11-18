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

Each section holds text (a line such as "Nothing." counts); an HTML comment
alone is no text, since the rendered page shows nothing there.

The page is read as CommonMark reads it, as far as headings and text go: a
byte order mark at the start is dropped; a fenced code block opens with three
or more backticks or tildes indented by at most three spaces and closes only
with a run of the same character at least as long (an unclosed one runs to the
end); a heading or an HTML comment inside it is code, not structure. A line
indented by four spaces or more is an indented code block, so it opens no
fence and is no heading; its content counts as text. An HTML comment that
starts a line opens a block up to its `-->` (or the end), and a heading inside
it is no heading.

`check` (ci, every pull request): the hub's version is the one in
hub/pyproject.toml. Once CHANGELOG.md has that version's section (the release
pull request folds it in), its page must exist and be complete; before that,
nothing is asked. `--version X` checks the page of X whatever CHANGELOG.md says;
tools/release_gate.py asks for the tagged version this way. `check` also asks,
always, that docs/upgrade/README.md links every version page in docs/upgrade/:
the docs site renders only that README (docs/nav.yml), so its links are the way
a reader of the site finds the version pages.
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
# CommonMark: an ATX heading and a fence are indented by at most three spaces.
HEADING = re.compile(r"^ {0,3}## (.*)$")
FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
COMMENT_START = re.compile(r"^ {0,3}<!--")
# An HTML comment, or an unclosed one up to the end of the section.
COMMENT = re.compile(r"<!--.*?(?:-->|\Z)", re.DOTALL)


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
    headings, bodies = sections(path.read_text(encoding="utf-8-sig"))
    found = [h for h in headings if h in SECTIONS]
    out = []
    missing = [s for s in SECTIONS if s not in found]
    if missing:
        out.append(f"{name} lacks the section(s): " + "; ".join(f"## {s}" for s in missing))
    elif found != list(SECTIONS) or len(set(found)) != len(found):
        out.append(f"{name}: the sections must appear once each, in this order: " + "; ".join(SECTIONS))
    for section in SECTIONS:
        if section in bodies and not has_text(*bodies[section]):
            out.append(f"{name}: '## {section}' is empty (write 'Nothing.' if nothing applies)")
    return out


def sections(text: str) -> tuple[list[str], dict[str, tuple[list[str], list[str]]]]:
    """The second-level headings in order, and per heading its body as (prose lines,
    code lines); the module's docstring has the rules."""
    headings: list[str] = []
    bodies: dict[str, tuple[list[str], list[str]]] = {}
    fence: str | None = None  # the opening run of the open fence
    comment = False
    for line in text.splitlines():
        body = bodies[headings[-1]] if headings else ([], [])
        if fence is not None:
            closing = FENCE.match(line)
            if (
                closing
                and closing.group(1)[0] == fence[0]
                and len(closing.group(1)) >= len(fence)
                and not closing.group(2).strip(" \t")
            ):
                # A fence line is no text of its own: an empty code block leaves a section empty.
                fence = None
            else:
                body[1].append(line)
            continue
        if comment:
            comment = "-->" not in line
            body[0].append(line)
            continue
        opening = FENCE.match(line)
        if opening and not (opening.group(1)[0] == "`" and "`" in opening.group(2)):
            fence = opening.group(1)
            continue
        heading = HEADING.match(line)
        if heading:
            headings.append(heading.group(1).strip())
            bodies[headings[-1]] = ([], [])
            continue
        start = COMMENT_START.match(line)
        if start and "-->" not in line[start.end() :]:
            comment = True
        body[0].append(line)
    return headings, bodies


def has_text(prose: list[str], code: list[str]) -> bool:
    """Whether a section's body shows anything: code, or prose besides HTML comments."""
    return any(line.strip() for line in code) or bool(COMMENT.sub("", "\n".join(prose)).strip())


def unlisted(root: Path) -> list[str]:
    """The version pages in docs/upgrade/ that docs/upgrade/README.md does not link."""
    folder = root / "docs" / "upgrade"
    readme = folder / "README.md"
    text = readme.read_text(encoding="utf-8-sig") if readme.is_file() else ""
    return [
        f"docs/upgrade/README.md does not link {page.name}: add the line"
        f" '- [{page.stem}]({page.name})' to its list of versions"
        for page in sorted(folder.glob("*.md"))
        if page.name != "README.md" and f"]({page.name})" not in text
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=["check"])
    parser.add_argument("--version", help="check this version's page, released or not")
    args = parser.parse_args(argv)
    version = args.version or hub_version(ROOT)
    found = unlisted(ROOT)
    if not args.version and not released(ROOT, version):
        print(f"hub {version} is not folded into CHANGELOG.md yet: no upgrade page asked")
        complete = None
    else:
        page = problems(ROOT, version)
        found += page
        complete = not page
    for problem in found:
        print(f"::error::{problem}")
    if complete:
        print(f"docs/upgrade/{version}.md: complete")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
