#!/usr/bin/env python3
"""Hold the README's translations to README.md.

    python3 tools/readme_sync.py            # what CI runs, with the changelog check

Every language of the web client (`web/js/i18n/languages.js`) but English has a
`README.<lang>.md` next to `README.md`. Each one:

- starts with `<!-- translated-from: README.md@<commit> -->`, the full hash of the
  `README.md` commit it was translated from (only its form is checked: CI's shallow
  checkout has no history to look the commit up in);
- has the language line, the same in every version, with its own language in bold;
- has as many headings as `README.md`, at the same levels in the same sequence;
- links the same targets and shows the same images as `README.md`.

`README.md` has the language line too. A section added to or dropped from `README.md`
without its translations, or a heading moved to another level, fails here rather than
going stale unnoticed. Heading text is not compared, so two sections of the same level
swapped, or one replaced by another, pass unless their links differ; the comment names the
commit to diff against when translating it (context/process.md, the entry on the
README's translations).

Standard library only. Prints every finding as `file:line: message` and exits 1.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Each language's own name, as the web client's language menu shows it
# (web/js/api.js, FRAME_NAMES).
NAMES = {
    "en": "English",
    "de": "Deutsch",
    "es": "Español",
    "fr": "Français",
    "it": "Italiano",
    "ja": "日本語",
    "ko": "한국어",
    "nl": "Nederlands",
    "pt": "Português",
    "zh-Hans": "简体中文",
}

ORIGIN = re.compile(r"<!-- translated-from: README\.md@([0-9a-f]{40}) -->")
FENCE = re.compile(r"^\s*(```|~~~)")
HEADING = re.compile(r"^(#{1,6})\s+\S")
HTML_HEADING = re.compile(r"^<h([1-6])[\s>]")
# The target of a Markdown link or image, and the src/srcset of an HTML image.
TARGET = re.compile(r"\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)|\b(?:src|srcset)=\"([^\"]+)\"")


def languages(root: Path = ROOT) -> list[str]:
    """The web client's languages, from its generated list."""
    text = (root / "web/js/i18n/languages.js").read_text(encoding="utf-8")
    found = re.search(r"MAITY_I18N_LANGUAGES\s*=\s*(\[[^\]]*\])", text)
    if found is None:
        raise SystemExit("web/js/i18n/languages.js: no MAITY_I18N_LANGUAGES list")
    tags: list[str] = json.loads(found.group(1))
    return tags


def file_of(lang: str) -> str:
    return "README.md" if lang == "en" else f"README.{lang}.md"


def language_line(lang: str, tags: list[str]) -> str:
    """English first, then the others in the list's order; the file's own in bold."""
    order = ["en"] + [t for t in tags if t != "en"]
    parts = [f"**{NAMES[t]}**" if t == lang else f"[{NAMES[t]}]({file_of(t)})" for t in order]
    return " · ".join(parts)


def outline(lines: list[str]) -> list[tuple[int, int]]:
    """(line number, level) of every heading outside fenced code."""
    found: list[tuple[int, int]] = []
    fenced = False
    for number, line in enumerate(lines, 1):
        if FENCE.match(line):
            fenced = not fenced
            continue
        if fenced:
            continue
        match = HEADING.match(line) or HTML_HEADING.match(line)
        if match:
            level = match.group(1)
            found.append((number, len(level) if level.startswith("#") else int(level)))
    return found


def targets(lines: list[str], skip: str) -> list[str]:
    """Every link and image target, in order, without the language line's."""
    found: list[str] = []
    for line in lines:
        if line == skip:
            continue
        for match in TARGET.finditer(line):
            found.append(match.group(1) or match.group(2))
    return found


def check(root: Path = ROOT) -> list[str]:
    tags = languages(root)
    unknown = [t for t in tags if t not in NAMES]
    if unknown:
        return [f"tools/readme_sync.py: no name for {', '.join(unknown)}; add it to NAMES"]
    findings: list[str] = []
    source = (root / "README.md").read_text(encoding="utf-8").splitlines()
    english = language_line("en", tags)
    if english not in source:
        findings.append(f"README.md:1: the language line is missing; it reads:\n  {english}")
    levels = [level for _, level in outline(source)]
    links = targets(source, english)
    for lang in tags:
        if lang == "en":
            continue
        name = file_of(lang)
        path = root / name
        if not path.is_file():
            findings.append(f"{name}:1: missing; translate README.md into {NAMES[lang]}")
            continue
        lines = path.read_text(encoding="utf-8").splitlines()
        if not lines or not ORIGIN.fullmatch(lines[0].strip()):
            findings.append(
                f"{name}:1: the first line must be "
                "<!-- translated-from: README.md@<full commit hash> -->"
            )
        own = language_line(lang, tags)
        if own not in lines:
            findings.append(f"{name}:1: the language line is missing; it reads:\n  {own}")
        heads = outline(lines)
        if [level for _, level in heads] != levels:
            findings.append(
                f"{name}:1: the headings differ from README.md "
                f"({len(heads)} here, {len(levels)} there, or at other levels); "
                "translate the sections README.md has added or moved"
            )
        if targets(lines, own) != links:
            findings.append(f"{name}:1: the links or images differ from README.md")
    return findings


def main(argv: list[str]) -> int:
    if argv:
        print(__doc__.strip().splitlines()[0], file=sys.stderr)
        print("usage: python3 tools/readme_sync.py", file=sys.stderr)
        return 2
    findings = check()
    for finding in findings:
        print(finding)
    if findings:
        return 1
    print(f"README: {len(languages()) - 1} translation(s), in sync with README.md's headings")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
