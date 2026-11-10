#!/usr/bin/env python3
"""Map each entry that was in web/context/views.md to the topic file it moved to.

The split is a move: an entry's id is the same, and its text is the text it
had in views.md. This reads those entries back out of the topic files.

    python3 tools/views_context_map.py
        One line per entry, id then topic file then heading, then a count
        per file.

    python3 tools/views_context_map.py <id>
        The line for that id. A unique prefix of the id is enough.

    python3 tools/views_context_map.py --hunk <file>
    python3 tools/views_context_map.py --hunk -
        A views.md diff hunk, or a piece of that file. Each entry the hunk
        touches is printed. An id the map does not have is printed as new,
        with the mapped entry the hunk places it beside, when one is there.

Standard library only. Run from anywhere; the files are found from this script.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONTEXT = ROOT / "web" / "context"

# The topic files views.md was split into, in the order their lines stand in
# the index.
FAMILIES = (
    "account",
    "admin",
    "agents",
    "board",
    "chat",
    "inbox",
    "jour-fixe",
    "members",
    "memory",
    "messages",
    "organisations",
    "overview",
    "people",
    "runners",
    "settings",
    "shell",
    "ticker",
    "why",
)

ID_RE = re.compile(
    r"\*\*Id:\*\* ([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})"
)
UUID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
)
# A line this short is a field almost every entry shares ("**Status:** active").
MIN_LINE = 24


@dataclass(frozen=True)
class Entry:
    id: str
    file: str
    heading: str
    lines: tuple[str, ...]


def entries_of(text: str) -> list[tuple[str, str, tuple[str, ...]]]:
    """(heading, id, lines) for each entry in a topic file. The H1 is skipped."""
    if "\n## " not in text and not text.startswith("## "):
        return []
    title, _, body = text.partition("\n\n")
    if not title.startswith("# "):
        body = text
    parts = body.split("\n## ")
    found = []
    for index, part in enumerate(parts):
        if index:
            part = "## " + part
        if not part.startswith("## "):
            continue
        heading = part.split("\n", 1)[0][3:]
        ids = ID_RE.findall(part)
        if len(ids) != 1:
            raise SystemExit(f"{heading!r} has {len(ids)} Id lines")
        found.append((heading, ids[0], tuple(part.splitlines())))
    return found


def load(context: Path = CONTEXT) -> list[Entry]:
    """The moved entries, in family order and then the order inside the file."""
    out: list[Entry] = []
    seen: set[str] = set()
    for name in FAMILIES:
        path = context / f"{name}.md"
        if not path.is_file():
            raise SystemExit(f"missing {path}")
        for heading, entry_id, lines in entries_of(path.read_text(encoding="utf-8")):
            if entry_id in seen:
                raise SystemExit(f"id {entry_id} is in more than one topic file")
            seen.add(entry_id)
            out.append(Entry(entry_id, f"{name}.md", heading, lines))
    return out


def line_index(entries: list[Entry]) -> dict[str, Entry]:
    """Lines that belong to exactly one entry. Shared field lines are left out."""
    owners: dict[str, Entry | None] = {}
    for entry in entries:
        for line in entry.lines:
            if len(line) < MIN_LINE:
                continue
            if line not in owners:
                owners[line] = entry
            elif owners[line] is not entry:
                owners[line] = None
    return {line: entry for line, entry in owners.items() if entry is not None}


def is_diff(text: str) -> bool:
    return any(
        line.startswith("@@") or line.startswith("diff --git ")
        for line in text.splitlines()
    )


def hunk_lines(text: str) -> list[str]:
    """The file lines a hunk carries. A unified diff loses its first column."""
    if not is_diff(text):
        return text.splitlines()
    lines = []
    for raw in text.splitlines():
        if raw.startswith(("diff --git ", "index ", "--- ", "+++ ", "@@", "\\")):
            continue
        if raw[:1] in " +-":
            raw = raw[1:]
        lines.append(raw)
    return lines


def match_hunk(text: str, entries: list[Entry]) -> list[tuple[str, str, str]]:
    """Rows for a hunk: (id, file or 'new', note).

    A mapped entry's note is its heading. A new id's note says it is not in
    the map and, when the hunk sits against a mapped entry, which one.
    """
    by_id = {entry.id: entry for entry in entries}
    by_line = line_index(entries)
    rows: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    last_mapped: Entry | None = None

    def add_mapped(entry: Entry) -> None:
        nonlocal last_mapped
        last_mapped = entry
        if entry.id in seen:
            return
        seen.add(entry.id)
        rows.append((entry.id, entry.file, entry.heading))

    for line in hunk_lines(text):
        stripped = line.strip()
        if not stripped:
            continue
        id_line = ID_RE.search(line)
        if id_line:
            entry_id = id_line.group(1)
            entry = by_id.get(entry_id)
            if entry is None:
                if entry_id not in seen:
                    seen.add(entry_id)
                    if last_mapped is None:
                        note = "not in the views.md map"
                    else:
                        note = (
                            "not in the views.md map; "
                            f"beside {last_mapped.id} in {last_mapped.file}"
                        )
                    rows.append((entry_id, "new", note))
            else:
                add_mapped(entry)
            continue
        owner = by_line.get(line)
        if owner is not None:
            add_mapped(owner)
    return rows


def resolve(entries: list[Entry], text: str) -> list[Entry]:
    """The entries whose id is `text` or, when that misses, starts with it."""
    exact = [entry for entry in entries if entry.id == text]
    if exact:
        return exact
    return [entry for entry in entries if entry.id.startswith(text)]


def format_row(entry_id: str, file: str, note: str) -> str:
    return f"{entry_id}\t{file}\t{note}"


def print_summary(entries: list[Entry]) -> None:
    for entry in entries:
        print(format_row(entry.id, entry.file, entry.heading))
    print(f"{len(entries)} entries")
    counts: dict[str, int] = {}
    for entry in entries:
        counts[entry.file] = counts.get(entry.file, 0) + 1
    for name in FAMILIES:
        file = f"{name}.md"
        if file in counts:
            print(f"{file}\t{counts[file]}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("id", nargs="?", help="an entry id, or a unique prefix of one")
    parser.add_argument(
        "--hunk",
        metavar="FILE",
        help="a views.md hunk; - reads stdin",
    )
    args = parser.parse_args(argv)
    if args.id and args.hunk:
        print("give an id or a hunk, not both", file=sys.stderr)
        return 2
    try:
        entries = load()
    except SystemExit as exc:
        print(exc, file=sys.stderr)
        return 2
    if args.hunk:
        if args.hunk == "-":
            text = sys.stdin.read()
        else:
            path = Path(args.hunk)
            if not path.is_file():
                print(f"no such hunk file: {args.hunk}", file=sys.stderr)
                return 2
            text = path.read_text(encoding="utf-8")
        rows = match_hunk(text, entries)
        if not rows:
            print("no views.md entry in this hunk")
            return 1
        for row in rows:
            print(format_row(*row))
        return 0
    if args.id:
        found = resolve(entries, args.id)
        if len(found) == 1:
            entry = found[0]
            print(format_row(entry.id, entry.file, entry.heading))
            return 0
        if not found:
            print(f"not in the views.md map: {args.id}")
            return 1
        print(f"{args.id} matches {len(found)} entries", file=sys.stderr)
        for entry in found:
            print(format_row(entry.id, entry.file, entry.heading))
        return 1
    print_summary(entries)
    return 0


if __name__ == "__main__":
    sys.exit(main())
