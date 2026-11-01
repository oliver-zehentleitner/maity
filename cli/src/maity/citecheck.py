"""Do a review's cites stand at the commit it names? (docs/api.md §8.4, §13)

The hub stores cites as given and does not read the repository, so an invented quote
reaches the lead. The clone that wrote the review can read them. This checks the quotes,
not whether the review is right. A malformed review is left alone: the hub names its bad
fields (§8.4).
"""

from __future__ import annotations

import dataclasses
import json
import re
import subprocess
from pathlib import Path
from typing import Any

from maity import proc

_FULL_SHA = re.compile(r"[0-9a-f]{40}")


@dataclasses.dataclass(frozen=True)
class Result:
    bad: list[str]  # one line per cite that does not stand at the commit
    unchecked: str | None = None  # why nothing could be checked


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return proc.run([*proc.GIT, "--literal-pathspecs", *args], cwd)


def _well_formed(cite: Any) -> bool:
    if not isinstance(cite, dict):
        return False
    path, quote, line = cite.get("path"), cite.get("quote"), cite.get("line")
    if not (isinstance(path, str) and path and isinstance(quote, str) and quote):
        return False
    return line is None or (type(line) is int and line > 0)


def _removed(cwd: Path, head: str, path: str, quote: str) -> bool:
    """A cite without a line may quote what the change removed (§8.4): the text then left
    the file somewhere in the commit's history, and the base of the change is not known here."""
    found = _git(cwd, "log", "-1", "--format=%H", f"-S{quote}", head, "--", path)
    return found.returncode == 0 and bool(found.stdout.strip())


def _problem(cwd: Path, head: str, path: str, line: int | None, quote: str) -> str | None:
    shown = _git(cwd, "show", f"{head}:{path}")
    lines = shown.stdout.split("\n") if shown.returncode == 0 else None
    if line is None:
        if lines is not None and any(quote in text for text in lines):
            return None
        if _removed(cwd, head, path, quote):
            return None
        return "the quote is neither in the file nor removed from it"
    if lines is None:
        return "the file is not at this commit"
    if line <= len(lines) and quote in lines[line - 1]:
        return None
    elsewhere = [number for number, text in enumerate(lines, 1) if quote in text]
    if elsewhere:
        return f"the quote is not on this line, it stands on line {elsewhere[0]}"
    return "the quote is not in the file"


def check(cwd: Path, review: Any) -> Result:
    if not isinstance(review, dict):
        return Result([])
    head, cites = review.get("head"), review.get("cites")
    if not (isinstance(head, str) and _FULL_SHA.fullmatch(head) and isinstance(cites, list)):
        return Result([])
    try:
        if _git(cwd, "rev-parse", "--git-dir").returncode != 0:
            return Result([], "this directory is not a clone")
        if _git(cwd, "cat-file", "-e", f"{head}^{{commit}}").returncode != 0:
            return Result([], f"commit {head} is not in this clone; `git fetch` brings it")
        bad = []
        for index, cite in enumerate(cites):
            if not _well_formed(cite):
                continue
            path, line, quote = cite["path"], cite.get("line"), cite["quote"]
            problem = _problem(cwd, head, path, line, quote)
            if problem is not None:
                place = f"{path}:{line}" if line is not None else path
                bad.append(f"review.cites.{index} {place}: {problem}: {json.dumps(quote)}")
    except proc.ToolError as exc:
        return Result([], str(exc))
    return Result(bad)
