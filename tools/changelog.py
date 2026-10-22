#!/usr/bin/env python3
"""Changelog fragments: one file per pull request in changelog.d/, folded into
CHANGELOG.md at release. Python 3.11+, standard library only.

    python3 tools/changelog.py check
        Validate every fragment in changelog.d/; exit 1 with file:line on error.

    python3 tools/changelog.py release <version> [--date YYYY-MM-DD] [--dry-run]
        Move everything under [Unreleased] in CHANGELOG.md and every fragment
        into a new `## [<version>] - <date>` section, headings in Keep a
        Changelog order, fragments by file name within each heading; leave
        [Unreleased] with its pointer line only; delete the fragments.

The fragment format is in changelog.d/README.md.
"""

from __future__ import annotations

import argparse
import datetime
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Keep a Changelog 1.1.0, in its order.
HEADINGS = ("Added", "Changed", "Deprecated", "Removed", "Fixed", "Security")

UNRELEASED = "## [Unreleased]"
FRAGMENT_DIR = "changelog.d"
FRAGMENT_SKIP = {"README.md"}
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.+-]+)?$")


class ChangelogError(Exception):
    """A finding to print; the message carries file:line where there is one."""


@dataclass
class Sections:
    """Entries per heading; an entry is a bullet line plus its continuation lines."""

    entries: dict[str, list[list[str]]] = field(default_factory=lambda: {h: [] for h in HEADINGS})

    def count(self) -> int:
        return sum(len(e) for e in self.entries.values())

    def extend(self, other: Sections) -> None:
        for heading in HEADINGS:
            self.entries[heading].extend(other.entries[heading])


def parse_sections(lines: list[str], where: str, first_line: int = 1) -> tuple[Sections, list[str]]:
    """Parse `### Heading` / `- bullet` lines. Returns the sections and the findings.

    Blank lines are separators. A line indented by whitespace continues the
    bullet above it. Anything else is a finding.
    """
    sections = Sections()
    errors: list[str] = []
    heading: str | None = None
    heading_line = 0
    heading_bullets = 0
    entry: list[str] | None = None

    def close_heading() -> None:
        if heading is not None and heading_bullets == 0:
            errors.append(f"{where}:{heading_line}: '### {heading}' has no bullet under it")

    for offset, raw in enumerate(lines):
        number = first_line + offset
        line = raw.rstrip("\n")
        if not line.strip():
            continue
        if line.startswith("#"):
            close_heading()
            entry = None
            match = re.fullmatch(r"### (\S.*?)\s*", line)
            if match is None or match.group(1) not in HEADINGS:
                errors.append(
                    f"{where}:{number}: heading {line.strip()!r} is not one of "
                    + ", ".join(f"'### {h}'" for h in HEADINGS)
                )
                heading = None
                continue
            heading = match.group(1)
            heading_line = number
            heading_bullets = 0
            continue
        if line.startswith("- "):
            if heading is None:
                errors.append(f"{where}:{number}: bullet outside a '### <heading>' section")
                entry = None
                continue
            entry = [line]
            sections.entries[heading].append(entry)
            heading_bullets += 1
            continue
        if line[0] in " \t" and entry is not None:
            entry.append(line)
            continue
        errors.append(
            f"{where}:{number}: expected '### <heading>', '- ' bullet or an indented "
            f"continuation line, got {line.strip()[:60]!r}"
        )
    close_heading()
    return sections, errors


def fragment_paths(root: Path) -> list[Path]:
    directory = root / FRAGMENT_DIR
    if not directory.is_dir():
        return []
    return sorted(p for p in directory.iterdir() if p.is_file() and p.name not in FRAGMENT_SKIP)


def read_fragments(root: Path) -> tuple[Sections, list[Path], list[str]]:
    """All fragments merged in file-name order, the files, and every finding."""
    merged = Sections()
    errors: list[str] = []
    paths = fragment_paths(root)
    for path in paths:
        where = path.relative_to(root).as_posix()
        if path.suffix != ".md":
            errors.append(f"{where}:1: a fragment is a .md file")
            continue
        text = path.read_text(encoding="utf-8")
        sections, found = parse_sections(text.splitlines(), where)
        if not found and sections.count() == 0:
            found.append(f"{where}:1: empty fragment")
        errors.extend(found)
        merged.extend(sections)
    return merged, paths, errors


@dataclass
class Changelog:
    head: list[str]  # up to and including the [Unreleased] heading
    preamble: list[str]  # prose under [Unreleased] before its first ### heading
    body: list[str]  # the ### sections under [Unreleased]
    body_first_line: int
    tail: list[str]  # from the first released version on


def split_changelog(text: str) -> Changelog:
    lines = text.splitlines()
    try:
        start = lines.index(UNRELEASED)
    except ValueError:
        raise ChangelogError(f"CHANGELOG.md: no '{UNRELEASED}' line") from None
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    block = lines[start + 1 : end]
    first_heading = next((i for i, line in enumerate(block) if line.startswith("#")), len(block))
    return Changelog(
        head=lines[: start + 1],
        preamble=block[:first_heading],
        body=block[first_heading:],
        body_first_line=start + 2 + first_heading,
        tail=lines[end:],
    )


def render_sections(sections: Sections) -> list[str]:
    out: list[str] = []
    for heading in HEADINGS:
        entries = sections.entries[heading]
        if not entries:
            continue
        out += [f"### {heading}", ""]
        for entry in entries:
            out += entry
        out.append("")
    return out


def strip_blank(lines: list[str]) -> list[str]:
    start, end = 0, len(lines)
    while start < end and not lines[start].strip():
        start += 1
    while end > start and not lines[end - 1].strip():
        end -= 1
    return lines[start:end]


def cmd_check(root: Path) -> int:
    _, paths, errors = read_fragments(root)
    for error in errors:
        print(error, file=sys.stderr)
    if errors:
        return 1
    print(f"changelog.d: {len(paths)} fragment(s), all valid")
    return 0


def cmd_release(root: Path, version: str, date: str | None, dry_run: bool) -> int:
    if not VERSION_RE.match(version):
        raise ChangelogError(f"version {version!r} is not semantic (1.2.3, 1.2.3-rc.1)")
    if date is None:
        date = datetime.date.today().isoformat()
    else:
        try:
            datetime.date.fromisoformat(date)
        except ValueError:
            raise ChangelogError(f"date {date!r} is not YYYY-MM-DD") from None
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
            raise ChangelogError(f"date {date!r} is not YYYY-MM-DD")

    path = root / "CHANGELOG.md"
    changelog = split_changelog(path.read_text(encoding="utf-8"))
    if any(re.match(rf"## \[{re.escape(version)}\]", line) for line in changelog.tail):
        raise ChangelogError(f"CHANGELOG.md: version {version} is already released")

    released, errors = parse_sections(changelog.body, "CHANGELOG.md", changelog.body_first_line)
    fragments, paths, fragment_errors = read_fragments(root)
    errors += fragment_errors
    if errors:
        raise ChangelogError("\n".join(errors))
    in_changelog = released.count()
    released.extend(fragments)
    if released.count() == 0:
        raise ChangelogError("nothing to release: [Unreleased] and changelog.d/ are empty")

    preamble = strip_blank(changelog.preamble)
    lines = changelog.head + [""]
    if preamble:
        lines += preamble + [""]
    lines += [f"## [{version}] - {date}", ""] + render_sections(released)
    if changelog.tail:
        lines += changelog.tail
    text = "\n".join(strip_blank(lines)) + "\n"

    print(
        f"## [{version}] - {date}: {released.count()} entries, "
        f"{in_changelog} from CHANGELOG.md [Unreleased], "
        f"{fragments.count()} from {len(paths)} fragment(s)"
    )
    for heading in HEADINGS:
        if released.entries[heading]:
            print(f"  ### {heading}: {len(released.entries[heading])}")
    if dry_run:
        print()
        print("\n".join([f"## [{version}] - {date}", ""] + render_sections(released)))
        print("dry run: CHANGELOG.md not written, nothing deleted")
        for p in paths:
            print(f"  would delete {p.relative_to(root).as_posix()}")
        return 0
    path.write_text(text, encoding="utf-8")
    for p in paths:
        p.unlink()
        print(f"  deleted {p.relative_to(root).as_posix()}")
    print("CHANGELOG.md written")
    return 0


def main(argv: list[str] | None = None, root: Path = ROOT) -> int:
    parser = argparse.ArgumentParser(prog="changelog.py", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("check", help="validate every fragment in changelog.d/")
    release = sub.add_parser("release", help="fold [Unreleased] and the fragments into a version")
    release.add_argument("version")
    release.add_argument("--date", help="YYYY-MM-DD, default today")
    release.add_argument("--dry-run", action="store_true", help="print, write and delete nothing")
    args = parser.parse_args(argv)
    try:
        if args.command == "check":
            return cmd_check(root)
        return cmd_release(root, args.version, args.date, args.dry_run)
    except ChangelogError as error:
        print(error, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
