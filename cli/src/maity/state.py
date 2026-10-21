"""Per-clone state: where the session credential and the local state live.

Layout (see cli/context/credentials.md for why):

    <git common dir>/maity/          mode 0700
        credential                   mode 0600, the session credential and nothing else
        state.json                   mode 0600, hub URL, project, identity, event cursor

Nothing in this module prints, logs or puts the credential into an exception message.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
from pathlib import Path
from typing import Any

STATE_DIR_ENV = "MAITY_STATE_DIR"
CREDENTIAL_FILE = "credential"
STATE_FILE = "state.json"


class StateError(Exception):
    """The state directory or a file in it cannot be used as it is."""


class Secret:
    """A value that refuses to be printed.

    `str()`, `repr()` and f-strings show a placeholder; the value is reachable only through
    `reveal()`, which is called where a request is built and nowhere else.
    """

    __slots__ = ("_value",)

    def __init__(self, value: str) -> None:
        self._value = value

    def reveal(self) -> str:
        return self._value

    def __repr__(self) -> str:
        return "Secret(<redacted>)"

    __str__ = __repr__

    def __format__(self, spec: str) -> str:
        return repr(self)


def resolve_state_dir(cwd: Path | None = None) -> Path:
    """Return the state directory for the clone `cwd` belongs to.

    `MAITY_STATE_DIR` wins. Otherwise the Git common directory of the clone (shared by its
    worktrees) plus `maity/`. Outside a Git clone, refuse: a home-level fallback would merge
    every agent profile on a shared home into one identity.
    """
    override = os.environ.get(STATE_DIR_ENV)
    if override:
        return Path(override).expanduser().resolve()
    base = cwd or Path.cwd()
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--git-common-dir"],
            cwd=base,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError as exc:
        raise StateError(f"git is not installed; set {STATE_DIR_ENV} to a directory") from exc
    if proc.returncode != 0:
        raise StateError(
            f"{base} is not inside a Git clone; run maity from the clone the agent works in, "
            f"or set {STATE_DIR_ENV} to a directory of its own"
        )
    common = Path(proc.stdout.strip())
    if not common.is_absolute():
        common = base / common
    return common.resolve() / "maity"


def _ensure_dir(path: Path) -> None:
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(path, 0o700)


def _atomic_write(path: Path, data: str) -> None:
    """Write `data` to `path` with mode 0600, never leaving a partly written file behind."""
    _ensure_dir(path.parent)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def _check_private(path: Path) -> None:
    """Refuse a file that others could read, the way ssh refuses a loose private key."""
    st = path.stat()
    if st.st_uid != os.getuid():
        raise StateError(f"{path} belongs to another user; refusing to use it")
    if st.st_mode & (stat.S_IRWXG | stat.S_IRWXO):
        mode = stat.S_IMODE(st.st_mode)
        raise StateError(
            f"{path} is accessible by group or others (mode {mode:04o}); "
            f"run `chmod 600 {path}` if the file is yours, or revoke the session in the dashboard"
        )


def credential_path(state_dir: Path) -> Path:
    return state_dir / CREDENTIAL_FILE


def has_credential(state_dir: Path) -> bool:
    return credential_path(state_dir).is_file()


def write_credential(state_dir: Path, value: Secret) -> Path:
    """Store the session credential, byte for byte, without a trailing newline.

    The same file the page-driven join writes with `curl -o` (docs/api.md §3.3), so a curl
    config built from it with `cat` stays valid. Returns the path, never the value.
    """
    text = value.reveal().strip()
    if not text or any(ch.isspace() for ch in text):
        raise StateError("refusing to store an empty credential or one containing whitespace")
    path = credential_path(state_dir)
    _atomic_write(path, text)
    return path


def read_credential(state_dir: Path) -> Secret:
    path = credential_path(state_dir)
    if not path.is_file():
        raise StateError(f"no session credential in {state_dir}; run `maity join` first")
    _check_private(path)
    value = path.read_text(encoding="utf-8").strip()
    if not value:
        raise StateError(f"{path} is empty; run `maity join` again")
    return Secret(value)


def load_state(state_dir: Path) -> dict[str, Any]:
    path = state_dir / STATE_FILE
    if not path.is_file():
        return {}
    _check_private(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise StateError(f"{path} is not valid JSON: {exc.msg}") from exc
    if not isinstance(data, dict):
        raise StateError(f"{path} does not hold a JSON object")
    return data


def save_state(state_dir: Path, data: dict[str, Any]) -> Path:
    path = state_dir / STATE_FILE
    _atomic_write(path, json.dumps(data, indent=2, sort_keys=True) + "\n")
    return path
