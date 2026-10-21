"""The pointer block `maity join` writes into AGENTS.md (docs/architecture.md §4.2).

It says that the repository is a Maity project and that a session runs `maity resume` at its
start. It points and nothing more: no URL to fetch, no secret, no rules (those come from the hub
in the resume packet). Whether it is committed is the repository's choice.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

BEGIN = "<!-- maity:begin -->"
END = "<!-- maity:end -->"
BLOCK = f"""{BEGIN}
## Maity

This repository is a Maity project. At the start of every session, and after a
context compaction, run `maity resume` from this clone: it says who you are, what
you hold, and what you missed. `maity --help` lists the other commands.
{END}
"""


def repo_root(cwd: Path) -> Path | None:
    cmd = ["git", "rev-parse", "--show-toplevel"]
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=False)
    return Path(proc.stdout.strip()) if proc.returncode == 0 else None


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
