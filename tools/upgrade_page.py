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
indented by four columns or more (spaces, a tab counting to the next multiple
of four) is an indented code block unless it continues paragraph text (the
line before is a non-blank text line); code opens no fence and is no heading,
and its content, comments too, counts as text. An HTML comment that starts a
line opens a block up to its `-->` (or the end), and a heading inside it is no
heading. Not followed: list items, so a line indented four columns inside one
is read as code, a fence there too.

`check` (ci, every pull request): the hub's version is the one in
hub/pyproject.toml. Once CHANGELOG.md has that version's section (the release
pull request folds it in), its page must exist and be complete; before that,
nothing is asked. `--version X` checks the page of X whatever CHANGELOG.md says;
tools/release_gate.py asks for the tagged version this way. `check` also asks,
always, that docs/upgrade/README.md links every version page in docs/upgrade/:
the docs site renders only that README (docs/nav.yml), so its links are the way
a reader of the site finds the version pages. Only links the rendered README
shows count, never ones in a code block, a code span or an HTML comment: an
inline link `[text](dest)` (not an image), or a reference link `[text][label]`,
`[label][]` or `[label]` whose definition `[label]: dest` starts a paragraph.
A destination names a page after its angle brackets and `#fragment` are
dropped and its path is normalised, so `<./0.1.0a9.md#top>` names 0.1.0a9.md.
Standard library only.
"""

from __future__ import annotations

import argparse
import posixpath
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
ATX = re.compile(r"^ {0,3}#{1,6}(?:[ \t]|$)")
FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
COMMENT_START = re.compile(r"^ {0,3}<!--")
# An HTML comment, or an unclosed one up to the end of the section.
COMMENT = re.compile(r"<!--.*?(?:-->|\Z)", re.DOTALL)
# Links, within one paragraph: an inline link (not an image), a reference definition, a use of a label.
INLINE_LINK = re.compile(
    r"(?<!!)\[[^\[\]]*\]\(\s*(<[^<>\n]*>|[^\s()<>]+)(?:\s+(?:\"[^\"]*\"|'[^']*'|\([^()]*\)))?\s*\)"
)
LINK_DEF = re.compile(r"^ {0,3}\[([^\[\]]+)\]:[ \t]*(<[^<>\n]*>|\S+)")
REF_USE = re.compile(r"(?<!!)\[([^\[\]]+)\](?!\()")
CODE_SPAN = re.compile(r"(?<!`)(`+)(?!`).+?(?<!`)\1(?!`)", re.DOTALL)


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


def indent(line: str) -> int:
    """The columns of a line's leading spaces and tabs, a tab counting to the next multiple of four."""
    width = 0
    for char in line:
        if char == " ":
            width += 1
        elif char == "\t":
            width += 4 - width % 4
        else:
            break
    return width


def lines(text: str) -> list[tuple[str, str]]:
    """Each line of a page with its kind: "heading" (a `##` heading, given as its title),
    "code" (in a fenced or indented code block) or "text"; fence lines are left out.
    The module's docstring has the rules."""
    out: list[tuple[str, str]] = []
    fence: str | None = None  # the opening run of the open fence
    comment = False
    paragraph = False  # the line before is paragraph text, which an indented line continues
    for line in text.splitlines():
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
                out.append(("code", line))
            continue
        if comment:
            comment = "-->" not in line
            out.append(("text", line))
            continue
        if not line.strip(" \t"):
            paragraph = False
            out.append(("text", line))
            continue
        if indent(line) >= 4 and not paragraph:
            out.append(("code", line))
            continue
        opening = FENCE.match(line)
        if opening and not (opening.group(1)[0] == "`" and "`" in opening.group(2)):
            fence = opening.group(1)
            paragraph = False
            continue
        heading = HEADING.match(line)
        if heading:
            out.append(("heading", heading.group(1).strip()))
            paragraph = False
            continue
        start = COMMENT_START.match(line)
        if start:
            comment = "-->" not in line[start.end() :]
            paragraph = False
        else:
            paragraph = not ATX.match(line)
        out.append(("text", line))
    return out


def sections(text: str) -> tuple[list[str], dict[str, tuple[list[str], list[str]]]]:
    """The second-level headings in order, and per heading its body as (prose lines,
    code lines)."""
    headings: list[str] = []
    bodies: dict[str, tuple[list[str], list[str]]] = {}
    for kind, line in lines(text):
        if kind == "heading":
            headings.append(line)
            bodies[line] = ([], [])
        elif headings:
            bodies[headings[-1]][0 if kind == "text" else 1].append(line)
    return headings, bodies


def has_text(prose: list[str], code: list[str]) -> bool:
    """Whether a section's body shows anything: code, or prose besides HTML comments."""
    return any(line.strip() for line in code) or bool(COMMENT.sub("", "\n".join(prose)).strip())


def label(text: str) -> str:
    """A link label as CommonMark matches it: case and runs of whitespace do not count."""
    return " ".join(text.split()).casefold()


def destination(text: str) -> str:
    """A link destination without angle brackets and #fragment, its path normalised."""
    if text.startswith("<") and text.endswith(">"):
        text = text[1:-1]
    return posixpath.normpath(text.split("#", 1)[0] or ".")


def links(text: str) -> set[str]:
    """The destinations of the links a rendered page shows; the module's docstring has the rules."""
    rendered: list[str] = []
    for kind, line in lines(text):
        rendered += ["", line, ""] if kind == "heading" else [line if kind == "text" else ""]
    definitions: dict[str, str] = {}
    paragraphs: list[str] = []
    for paragraph in re.split(r"\n(?:[ \t]*\n)+", COMMENT.sub("", "\n".join(rendered))):
        rest = paragraph.split("\n")
        while rest and (found := LINK_DEF.match(rest[0])):
            definitions.setdefault(label(found.group(1)), found.group(2))
            rest = rest[1:]
        paragraphs.append(CODE_SPAN.sub("", "\n".join(rest)))
    targets = set()
    for paragraph in paragraphs:
        targets.update(found.group(1) for found in INLINE_LINK.finditer(paragraph))
        for found in REF_USE.finditer(paragraph):
            if label(found.group(1)) in definitions:
                targets.add(definitions[label(found.group(1))])
    return {destination(target) for target in targets}


def unlisted(root: Path) -> list[str]:
    """The version pages in docs/upgrade/ that docs/upgrade/README.md does not link."""
    folder = root / "docs" / "upgrade"
    readme = folder / "README.md"
    linked = links(readme.read_text(encoding="utf-8-sig")) if readme.is_file() else set()
    return [
        f"docs/upgrade/README.md does not link {page.name}: add the line"
        f" '- [{page.stem}]({page.name})' to its list of versions"
        for page in sorted(folder.glob("*.md"))
        if page.name != "README.md" and page.name not in linked
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
