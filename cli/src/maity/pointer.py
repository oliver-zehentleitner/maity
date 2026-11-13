"""The pointer block `maity join` writes into AGENTS.md (docs/architecture.md §4.2).

It says that the repository is a Maity project and that a session runs `maity resume` at its
start. It points to resume and the project communication channel: no URL to fetch, no secret,
no project rules (those come from the hub in the resume packet). Whether it is committed is
the repository's choice.
"""

from __future__ import annotations

import os
from pathlib import Path

from maity import proc

BEGIN = "<!-- maity:begin -->"
END = "<!-- maity:end -->"
# Where the platform has it (not Windows): a link put in place after the check is not followed.
_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_BINARY = getattr(os, "O_BINARY", 0)  # Windows: the text layer translates line ends, once
# The maintainer's request of 2026-10-27: once joined, an agent talks to its human through
# Maity alone, because the human follows many agents in one place, not in many chat windows.
HUMAN_CHANNEL = (
    "Once joined, talk to your human only through Maity: `maity say human` to chat, "
    "`maity ask --to human` for decisions and proposals, `maity report` for results. The "
    "harness terminal is only where your human starts you or unblocks a permission; if they "
    "write there, answer with one line that points to Maity. Your human follows many agents "
    "on several machines in one place, not in one chat window per agent."
)
PROJECT_CHANNEL = (
    "Maity is the project's main channel: use `maity say`, `maity ask` and `maity report` "
    "for work communication; bring project instructions from other chats onto the relevant "
    f"card or into a Maity message. {HUMAN_CHANNEL}"
)
SHELL_TEXT = (
    "Pass Markdown with `code` spans to `maity` as `-` with a quoted heredoc "
    "(`maity say <to> --type notice - <<'EOF'`) or with `--body-file`, never inline in double "
    "quotes: the shell runs backtick spans and `$(…)` before `maity` sees the text."
)
BLOCK = f"""{BEGIN}
## Maity

This repository is a Maity project. At the start of every session, and after a
context compaction, run `maity resume` from this clone: it says who you are, what
you hold, and what you missed. `maity --help` lists the other commands.

{SHELL_TEXT}

{PROJECT_CHANNEL}
{END}
"""


def repo_root(cwd: Path) -> Path | None:
    try:
        result = proc.run([*proc.GIT, "rev-parse", "--show-toplevel"], cwd)
    except proc.ToolError:
        return None
    return Path(result.stdout.strip()) if result.returncode == 0 else None


class Refused(Exception):
    """A file the block is not written into: a symbolic link, or a path outside the root."""


def _inside(root: Path, path: Path) -> Path:
    """`path` itself, refused when it is a symbolic link or does not resolve to a file directly
    in `root`. A clone can carry a link to anywhere (a file of the home directory, another
    repository's), and the join must not write through it."""
    if path.is_symlink():
        raise Refused(f"{path} is a symbolic link; the pointer block is written only into a file")
    if path.resolve().parent != root.resolve():
        raise Refused(f"{path} does not resolve inside {root}")
    return path


def _read(path: Path) -> str:
    """The file's text, opened without following a link swapped in after the check."""
    try:
        fd = os.open(path, os.O_RDONLY | _NOFOLLOW | _BINARY)
    except FileNotFoundError:
        return ""
    with os.fdopen(fd, encoding="utf-8") as fh:
        return fh.read()


def _upsert(path: Path) -> bool:
    """Insert or refresh the block; return True when the file changed."""
    text = _read(path)
    if BEGIN in text and END in text:
        head, rest = text.split(BEGIN, 1)
        tail = rest.split(END, 1)[1].lstrip("\n")
        new = head + BLOCK + tail
    elif not text or text.endswith("\n\n"):
        new = text + BLOCK
    else:
        new = text + ("\n" if text.endswith("\n") else "\n\n") + BLOCK
    if new == text:
        return False
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | _NOFOLLOW | _BINARY, 0o666)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(new)
    return True


def write(root: Path) -> tuple[list[Path], list[str]]:
    """Write the block into AGENTS.md, and into CLAUDE.md when the repository has one that does
    not already import AGENTS.md. Returns the files that changed and, for each file refused
    (`_inside`), why. A CLAUDE.md that is a link to this AGENTS.md is no refusal: the block is
    in it once AGENTS.md has it."""
    changed: list[Path] = []
    refused: list[str] = []
    agents = root / "AGENTS.md"
    try:
        if _upsert(_inside(root, agents)):
            changed.append(agents)
    except Refused as exc:
        refused.append(str(exc))
    claude = root / "CLAUDE.md"
    if claude.is_symlink() and claude.resolve() == agents.resolve() and not agents.is_symlink():
        return changed, refused
    if not (claude.is_file() or claude.is_symlink()):
        return changed, refused
    try:
        _inside(root, claude)
        if "@AGENTS.md" not in _read(claude) and _upsert(claude):
            changed.append(claude)
    except Refused as exc:
        refused.append(str(exc))
    return changed, refused
