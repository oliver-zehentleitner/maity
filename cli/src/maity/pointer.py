"""The pointer block `maity join` writes into AGENTS.md (docs/architecture.md §4.2).

It says that the repository is a Maity project and that a session runs `maity resume` at its
start. It points to resume and the project communication channel: no URL to fetch, no secret,
no project rules (those come from the hub in the resume packet). Whether it is committed is
the repository's choice.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

from maity import proc

BEGIN = "<!-- maity:begin -->"
END = "<!-- maity:end -->"
# Where the platform has it (not Windows): a link put in place after the check is not followed.
_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_BINARY = getattr(os, "O_BINARY", 0)  # Windows: the text layer translates line ends, once
_NONBLOCK = getattr(os, "O_NONBLOCK", 0)  # a FIFO swapped in does not hang the join
# Where the platform opens relative to a directory (not Windows): the files are opened in the
# root directory opened once, so a directory swapped for another path later is not followed.
_DIR_FD = os.open in os.supports_dir_fd and hasattr(os, "O_DIRECTORY")
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
    """A file the block is not written into: a symbolic link, no regular file, a path outside
    the root, or one the system would not open."""


class _Root:
    """The repository's root, opened once where the platform allows it: every file below is
    looked up in that directory, not by a path that could lead elsewhere by the time it is
    opened. Elsewhere (Windows) the files are opened by path after the check."""

    def __init__(self, root: Path) -> None:
        self.path = root
        self.fd: int | None = None
        if _DIR_FD:
            try:
                self.fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | _NOFOLLOW)
            except OSError as exc:
                raise Refused(f"{root} cannot be opened as a directory ({exc.strerror})") from exc

    def close(self) -> None:
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None

    def lstat(self, name: str) -> os.stat_result | None:
        """The entry itself, a link not followed; None when there is none."""
        try:
            if self.fd is not None:
                return os.stat(name, dir_fd=self.fd, follow_symlinks=False)
            return os.lstat(self.path / name)
        except FileNotFoundError:
            return None

    def stat(self, name: str) -> os.stat_result | None:
        """What the entry leads to (metadata only); None when nothing."""
        try:
            if self.fd is not None:
                return os.stat(name, dir_fd=self.fd)
            return os.stat(self.path / name)
        except OSError:
            return None

    def open(self, name: str, flags: int) -> int:
        flags |= _NOFOLLOW | _BINARY
        if self.fd is not None:
            return os.open(name, flags, 0o666, dir_fd=self.fd)
        path = self.path / name
        if path.resolve().parent != self.path.resolve():
            raise Refused(f"{path} does not resolve inside {self.path}")
        return os.open(path, flags, 0o666)


def _check(root: _Root, name: str) -> None:
    """Refuse an entry that is a symbolic link or no regular file. A clone can carry a link to
    anywhere (a file of the home directory, another repository's), and the join must not
    write through it."""
    entry = root.lstat(name)
    if entry is None:
        return
    if stat.S_ISLNK(entry.st_mode):
        raise Refused(
            f"{root.path / name} is a symbolic link; the pointer block is written only into a file"
        )
    if not stat.S_ISREG(entry.st_mode):
        raise Refused(f"{root.path / name} is not a regular file")


def _regular(fd: int, path: Path) -> None:
    if not stat.S_ISREG(os.fstat(fd).st_mode):
        os.close(fd)
        raise Refused(f"{path} is not a regular file")


def _read(root: _Root, name: str) -> str:
    """The file's text, opened in the root without following a link swapped in after the
    check; "" when there is none."""
    try:
        fd = root.open(name, os.O_RDONLY | _NONBLOCK)
    except FileNotFoundError:
        return ""
    _regular(fd, root.path / name)
    with os.fdopen(fd, encoding="utf-8") as fh:
        return fh.read()


def _upsert(root: _Root, name: str) -> bool:
    """Insert or refresh the block; return True when the file changed."""
    _check(root, name)
    text = _read(root, name)
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
    fd = root.open(name, os.O_WRONLY | os.O_CREAT | _NONBLOCK)
    _regular(fd, root.path / name)  # before anything is truncated
    os.ftruncate(fd, 0)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(new)
    return True


def _refusal(path: Path, exc: OSError) -> str:
    return f"{path} could not be written ({exc.strerror or exc})"


def write(root: Path) -> tuple[list[Path], list[str]]:
    """Write the block into AGENTS.md, and into CLAUDE.md when the repository has one that does
    not already import AGENTS.md. Returns the files that changed and, for each file refused
    (a link, no regular file, outside the root, or an error opening or writing it), why. A
    CLAUDE.md that is a link to this AGENTS.md is no refusal: the block is in it once
    AGENTS.md has it."""
    changed: list[Path] = []
    refused: list[str] = []
    agents, claude = root / "AGENTS.md", root / "CLAUDE.md"
    try:
        opened = _Root(root)
    except Refused as exc:
        return changed, [str(exc)]
    try:
        try:
            if _upsert(opened, "AGENTS.md"):
                changed.append(agents)
        except Refused as exc:
            refused.append(str(exc))
        except OSError as exc:
            refused.append(_refusal(agents, exc))
        entry = opened.lstat("CLAUDE.md")
        if entry is None:
            return changed, refused
        if stat.S_ISLNK(entry.st_mode):
            target, own = opened.stat("CLAUDE.md"), opened.lstat("AGENTS.md")
            if (
                target is not None
                and own is not None
                and stat.S_ISREG(own.st_mode)
                and os.path.samestat(target, own)
            ):
                return changed, refused
        elif not stat.S_ISREG(entry.st_mode):
            return changed, refused  # a directory of that name is no CLAUDE.md, as before
        try:
            _check(opened, "CLAUDE.md")
            if "@AGENTS.md" not in _read(opened, "CLAUDE.md") and _upsert(opened, "CLAUDE.md"):
                changed.append(claude)
        except Refused as exc:
            refused.append(str(exc))
        except OSError as exc:
            refused.append(_refusal(claude, exc))
    finally:
        opened.close()
    return changed, refused
