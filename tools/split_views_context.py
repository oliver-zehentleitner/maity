#!/usr/bin/env python3
"""Rebuild the web/context views split from a views.md.

The assignment table is tools/views_families.tsv (one ``id<TAB>family`` line,
in the order the entries had in the views.md it was made from). An id that is
not in the table is an error. ``--family ID=family`` classifies one such id
for this run only; it is not written back into the table.

    python3 tools/split_views_context.py --views web/context/views.md --check
    python3 tools/split_views_context.py --views web/context/views.md --write DIR
    python3 tools/split_views_context.py --views V --index I --write DIR --family ID=shell

``--check`` builds the topic files, the index and the See and prose locators
in memory and compares them with web/context here. It prints the lossless
counts and exits 1 when a byte differs, an id is missing, extra or repeated,
or a live ``views.md`` reference remains outside ``changelog.d/``,
the root ``CHANGELOG.md``, ``web/vendor/`` and ``tools/``. The files it
writes are refused if they still name ``views.md``. ``dashboard-views.md``
is not that file.

Standard library only.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONTEXT = ROOT / "web" / "context"
TABLE = Path(__file__).resolve().parent / "views_families.tsv"
SUMMARIES = Path(__file__).resolve().parent / "views_index_summaries.json"

TITLES = {
    "account": "Account",
    "admin": "Administration",
    "agents": "Agents",
    "board": "Board",
    "chat": "Chat",
    "inbox": "Inbox",
    "jour-fixe": "Jour fixe",
    "members": "Members",
    "memory": "Memory",
    "messages": "Messages",
    "organisations": "Organisations",
    "overview": "Overview",
    "people": "People",
    "runners": "Runners",
    "settings": "Settings",
    "shell": "Shell",
    "ticker": "Ticker",
    "why": "Why",
}

ID_RE = re.compile(
    r"\*\*Id:\*\* ([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})"
)
UUID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
)
SEE_RE = re.compile(
    r"^(\*\*See:\*\* )views\.md((?:#[A-Za-z0-9_-]*)? — "
    r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})"
    r" — as of [0-9]{4}-[0-9]{2}-[0-9]{2})$"
)
PROSE_ANCHOR_RE = re.compile(r"(?<![\w-])views\.md#([A-Za-z0-9_-]+)")
PROSE_COLON_RE = re.compile(r"(?<![\w-])views\.md:")
COMMA_UUID_RE = re.compile(
    r"(?<![\w-])views\.md(?=,\n([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}))"
)
ANCHOR_DROP = re.compile(r"[^\w\- ]", re.UNICODE)
FAMILY_ARG = re.compile(
    r"^([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})=([a-z0-9-]+)$"
)
# dashboard-views.md is the vendored library's document, not this split.
VIEWS_REF = re.compile(r"(?<![\w-])views\.md")
# Historical fragments describe a past edit. A release folds them into the
# root CHANGELOG.md, which a pull request is merged with and does not edit.
# Vendored files are not ours. The tools name views.md as the file they are
# given. The pre-split copies the tests read live under tools/fixtures/ and
# stay inside this skip: a views.md outside it is a live reference, so the
# skip is not widened for the copies.
LIVE_SKIP = ("changelog.d/", "web/vendor/", "tools/")
LIVE_SKIP_FILES = {"CHANGELOG.md"}


class Unclassified(Exception):
    def __init__(self, ids: list[str]) -> None:
        self.ids = ids
        super().__init__(
            "unclassified id (give --family ID=family, or add it to "
            "tools/views_families.tsv):\n" + "\n".join(ids)
        )


def anchor_of(heading: str) -> str:
    return ANCHOR_DROP.sub("", heading.strip().lower()).replace(" ", "-")


def load_table(path: Path = TABLE) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    seen: set[str] = set()
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not raw.strip() or raw.startswith("#"):
            continue
        parts = raw.split("\t")
        if len(parts) != 2 or not UUID_RE.fullmatch(parts[0]):
            raise SystemExit(f"{path}:{number}: want id<TAB>family")
        if parts[1] not in TITLES:
            raise SystemExit(f"{path}:{number}: unknown family {parts[1]!r}")
        if parts[0] in seen:
            raise SystemExit(f"{path}:{number}: duplicate id {parts[0]}")
        seen.add(parts[0])
        rows.append((parts[0], parts[1]))
    return rows


def load_summaries(path: Path = SUMMARIES) -> dict[str, str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    missing = [f"{name}.md" for name in TITLES if f"{name}.md" not in data]
    if missing:
        raise SystemExit(f"index summaries missing: {', '.join(missing)}")
    return data


def parse_entries(text: str) -> list[str]:
    if not text.startswith("# Views\n\n"):
        raise SystemExit("views.md does not start with '# Views' and a blank line")
    body = text[len("# Views\n\n") :]
    parts = body.split("\n## ")
    entries = []
    for index, part in enumerate(parts):
        if index:
            part = "## " + part
        if not part.startswith("## "):
            raise SystemExit("an entry does not start with a heading")
        entries.append(part)
    return entries


def heading_of(entry: str) -> str:
    return entry.split("\n", 1)[0][3:]


def id_of(entry: str) -> str:
    found = ID_RE.findall(entry)
    if len(found) != 1:
        raise SystemExit(f"{heading_of(entry)!r} has {len(found)} Id lines")
    return found[0]


def repair_locators(
    text: str,
    id_to_file: dict[str, str],
    id_to_anchor: dict[str, str],
    anchor_to_file: dict[str, str],
) -> tuple[str, int]:
    """Replace views.md in See lines and in prose locators. Returns the count."""
    count = 0

    def comma(match: re.Match[str]) -> str:
        nonlocal count
        target = id_to_file.get(match.group(1))
        if target is None:
            raise SystemExit(
                f"a views.md locator cites an id that is not in the split: {match.group(1)}"
            )
        count += 1
        return target

    text = COMMA_UUID_RE.sub(comma, text)
    lines = text.splitlines(keepends=True)
    out: list[str] = []
    for line in lines:
        newline = "\n" if line.endswith("\n") else ""
        raw = line[: -1] if newline else line
        see = SEE_RE.match(raw)
        if see:
            target = id_to_file.get(see.group(3))
            if target is None:
                raise SystemExit(f"See cites an id that is not in the split: {see.group(3)}")
            raw = see.group(1) + target + see.group(2)
            count += 1
            out.append(raw + newline)
            continue

        def prose(match: re.Match[str]) -> str:
            nonlocal count
            old_anchor = match.group(1)
            # A uuid later on the same line names the entry. The anchor is then
            # the heading's, so a locator that dropped a character is corrected.
            rest = raw[match.end() :]
            uuid = UUID_RE.search(rest)
            if uuid and uuid.group(0) in id_to_file:
                count += 1
                real = id_to_anchor[uuid.group(0)]
                return f"{id_to_file[uuid.group(0)]}#{real}"
            target = anchor_to_file.get(old_anchor)
            if target is None:
                return match.group(0)
            count += 1
            return f"{target}#{old_anchor}"

        raw = PROSE_ANCHOR_RE.sub(prose, raw)
        if PROSE_COLON_RE.search(raw):
            raw = PROSE_COLON_RE.sub("shell.md:", raw, count=1)
            count += 1
        out.append(raw + newline)
    return "".join(out), count


def classify(
    entries: list[str],
    table: list[tuple[str, str]],
    extra: dict[str, str],
) -> dict[str, list[str]]:
    known = {entry_id: family for entry_id, family in table}
    for entry_id, family in extra.items():
        if family not in TITLES:
            raise SystemExit(f"--family {entry_id}={family}: unknown family")
        known[entry_id] = family
    missing = []
    grouped: dict[str, list[str]] = {name: [] for name in TITLES}
    seen: set[str] = set()
    for entry in entries:
        entry_id = id_of(entry)
        if entry_id in seen:
            raise SystemExit(f"views.md repeats id {entry_id}")
        seen.add(entry_id)
        family = known.get(entry_id)
        if family is None:
            missing.append(entry_id)
            continue
        grouped[family].append(entry)
    if missing:
        raise Unclassified(missing)
    return grouped


def render_topic(family: str, entries: list[str]) -> str:
    body = f"# {TITLES[family]}\n\n" + "\n".join(entries)
    if not body.endswith("\n"):
        body += "\n"
    return body


def rebuild_index(index_text: str, summaries: dict[str, str]) -> str:
    intro, sep, rest = index_text.partition("\n## 0\n")
    if sep != "\n## 0\n" or not intro.startswith("# Context index\n"):
        raise SystemExit("index.md does not have the context-index skeleton")
    bullets: list[tuple[str, str]] = []
    for line in rest.splitlines():
        if not line.startswith("- ["):
            continue
        name = line.split("](", 1)[0][3:]
        if name == "views.md":
            continue
        bullets.append((name, line))
    for name, summary in summaries.items():
        bullets.append((name, f"- [{name}]({name}) \u2014 {summary}"))
    by_letter: dict[str, list[tuple[str, str]]] = {}
    for name, line in bullets:
        by_letter.setdefault(name[0].upper(), []).append((name, line))
    parts = [intro, "## 0"]
    letters = [str(n) for n in range(10)] + [chr(c) for c in range(ord("A"), ord("Z") + 1)]
    # ## 0 is already started; emit its bullets then the rest.
    chunks = [intro.rstrip("\n"), ""]
    for letter in letters:
        chunks.append(f"## {letter}")
        for _, line in sorted(by_letter.get(letter, []), key=lambda item: item[0]):
            chunks.append(line)
        chunks.append("")
    return "\n".join(chunks).rstrip("\n") + "\n"


def build(
    views_text: str,
    index_text: str,
    side_files: dict[str, str],
    table: list[tuple[str, str]],
    summaries: dict[str, str],
    extra: dict[str, str] | None = None,
) -> tuple[dict[str, str], dict[str, int]]:
    """Topic files, index and repaired side files. Counts are locator tokens per file."""
    entries = parse_entries(views_text)
    grouped = classify(entries, table, extra or {})
    id_to_file: dict[str, str] = {}
    id_to_anchor: dict[str, str] = {}
    anchor_to_file: dict[str, str] = {}
    for entry in entries:
        entry_id = id_of(entry)
        family = next(
            name for name, group in grouped.items() if any(id_of(item) == entry_id for item in group)
        )
        filename = f"{family}.md"
        id_to_file[entry_id] = filename
        anchor = anchor_of(heading_of(entry))
        id_to_anchor[entry_id] = anchor
        anchor_to_file.setdefault(anchor, filename)
    files: dict[str, str] = {}
    counts: dict[str, int] = {}
    for family, group in grouped.items():
        repaired = []
        total = 0
        for entry in group:
            text, n = repair_locators(entry, id_to_file, id_to_anchor, anchor_to_file)
            repaired.append(text)
            total += n
        files[f"web/context/{family}.md"] = render_topic(family, repaired)
        if total:
            counts[f"{family}.md"] = total
    files["web/context/index.md"] = rebuild_index(index_text, summaries)
    for name, text in side_files.items():
        updated, n = repair_locators(text, id_to_file, id_to_anchor, anchor_to_file)
        files[f"web/context/{name}"] = updated
        if n:
            counts[name] = counts.get(name, 0) + n
    assert_repairs_kept(files)
    return files, counts


def views_md_lines(text: str) -> list[int]:
    """Lines that name this split's views.md. dashboard-views.md does not count."""
    return [number for number, line in enumerate(text.splitlines(), 1) if VIEWS_REF.search(line)]


def live_views_references(root: Path) -> list[str]:
    """Live views.md references. Changelog fragments, vendored files and tools are skipped."""
    hits: list[str] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        if rel in LIVE_SKIP_FILES or rel.startswith(LIVE_SKIP) or rel.startswith(".git/"):
            continue
        if path.suffix.lower() not in {".md", ".js", ".py", ".yml", ".yaml", ".txt", ".html", ".css"} and path.name not in {
            "CONTRIBUTING.md",
            "AGENTS.md",
        }:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        hits.extend(f"{rel}:{number}" for number in views_md_lines(text))
    return hits


def assert_repairs_kept(produced: dict[str, str]) -> None:
    """The files this tool writes must not put views.md back."""
    left = [
        f"{relative}:{number}"
        for relative, text in sorted(produced.items())
        for number in views_md_lines(text)
    ]
    if left:
        raise SystemExit("generator left a views.md reference:\n" + "\n".join(left))


def lossless_report(views_text: str, produced: dict[str, str], counts: dict[str, int]) -> str:
    """Compare source entries with produced topic bodies. Trailing LF is not a difference."""
    originals = parse_entries(views_text)
    by_id = {id_of(entry): entry for entry in originals}
    seen: list[str] = []
    identical = 0
    changed_entries = 0
    lines = []
    for path, text in sorted(produced.items()):
        if not path.endswith(".md") or path.endswith("index.md"):
            continue
        if "/context/" not in path:
            continue
        family = Path(path).name
        if family[:-3] not in TITLES:
            continue
        title, _, body = text.partition("\n\n")
        parts = body.split("\n## ")
        for index, part in enumerate(parts):
            if index:
                part = "## " + part
            if not part.startswith("## "):
                continue
            entry_id = id_of(part)
            seen.append(entry_id)
            old = by_id[entry_id]
            if part.rstrip("\n") == old.rstrip("\n"):
                identical += 1
            else:
                changed_entries += 1
    dupes = len(seen) - len(set(seen))
    missing = sorted(set(by_id) - set(seen))
    extra = sorted(set(seen) - set(by_id))
    lines.append(f"old ids {len(by_id)}")
    lines.append(f"written ids {len(seen)} unique {len(set(seen))} duplicate {dupes}")
    lines.append(f"missing {len(missing)} extra {len(extra)}")
    lines.append(f"bodies identical under trailing LF {identical}")
    lines.append(f"bodies changed {changed_entries}")
    lines.append("locator tokens per file:")
    for name in sorted(counts):
        lines.append(f"{name}\t{counts[name]}")
    lines.append(f"locator tokens {sum(counts.values())}")
    if missing or extra or dupes or len(seen) != len(by_id):
        raise SystemExit("\n".join(lines))
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--views", required=True, help="the views.md to split")
    parser.add_argument("--index", help="index.md that still has the views.md line; default web/context/index.md")
    parser.add_argument("--write", metavar="DIR", help="write the context directory under DIR")
    parser.add_argument("--check", action="store_true", help="compare with web/context in this repository")
    parser.add_argument(
        "--family",
        action="append",
        default=[],
        metavar="ID=family",
        help="classify one id that the table does not list, for this run only",
    )
    args = parser.parse_args(argv)
    if not args.write and not args.check:
        print("give --check or --write DIR", file=sys.stderr)
        return 2
    extra: dict[str, str] = {}
    for item in args.family:
        match = FAMILY_ARG.match(item)
        if not match:
            print(f"--family wants ID=family, not {item!r}", file=sys.stderr)
            return 2
        extra[match.group(1)] = match.group(2)
    views_text = Path(args.views).read_text(encoding="utf-8")
    if args.index:
        index_text = Path(args.index).read_text(encoding="utf-8")
    else:
        index_text = (CONTEXT / "index.md").read_text(encoding="utf-8")
    if "- [views.md](" not in index_text:
        print(
            "index.md has no views.md line; pass --index with the index from before the split",
            file=sys.stderr,
        )
        return 2
    side: dict[str, str] = {}
    for name in ("refresh.md", "rendering.md"):
        side[name] = (CONTEXT / name).read_text(encoding="utf-8")
    try:
        produced, counts = build(
            views_text, index_text, side, load_table(), load_summaries(), extra
        )
    except Unclassified as exc:
        print(exc, file=sys.stderr)
        return 1
    report = lossless_report(views_text, produced, counts)
    if args.check:
        bad = []
        for relative, text in sorted(produced.items()):
            path = ROOT / relative
            if not path.is_file() or path.read_text(encoding="utf-8") != text:
                bad.append(relative)
        if bad:
            print(report, end="")
            print("differs:", ", ".join(bad), file=sys.stderr)
            return 1
        print(report, end="")
        print("matches web/context")
        live = live_views_references(ROOT)
        if live:
            print("live views.md reference:", file=sys.stderr)
            print("\n".join(live), file=sys.stderr)
            return 1
    if args.write:
        dest = Path(args.write)
        for relative, text in produced.items():
            path = dest / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        print(f"wrote {len(produced)} files under {dest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
