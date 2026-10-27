"""The pointer block `maity join` writes into AGENTS.md (docs/architecture.md §4.2).

It says that the repository is a Maity project and that a session runs `maity resume` at its
start. It points to resume and the project communication channel: no URL to fetch, no secret,
no project rules (those come from the hub in the resume packet). Whether it is committed is
the repository's choice.
"""

from __future__ import annotations

from pathlib import Path

from maity import proc

BEGIN = "<!-- maity:begin -->"
END = "<!-- maity:end -->"
PROJECT_CHANNEL = (
    "Maity is the project's main channel: use `maity say`, `maity ask` and `maity report` "
    "for work communication; bring project instructions from other chats onto the relevant "
    "card or into a Maity message."
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


def _upsert(path: Path) -> bool:
    """Insert or refresh the block; return True when the file changed."""
    text = path.read_text(encoding="utf-8") if path.exists() else ""
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
    path.write_text(new, encoding="utf-8")
    return True


def write(root: Path) -> list[Path]:
    """Write the block into AGENTS.md, and into CLAUDE.md when the repository has one that does
    not already import AGENTS.md. Returns the files that changed."""
    changed: list[Path] = []
    agents = root / "AGENTS.md"
    if _upsert(agents):
        changed.append(agents)
    claude = root / "CLAUDE.md"
    if claude.is_file() and "@AGENTS.md" not in claude.read_text(encoding="utf-8"):
        if _upsert(claude):
            changed.append(claude)
    return changed
