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
import secrets
import stat
import tempfile
from pathlib import Path
from typing import Any, SupportsIndex

from maity import proc

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

    def __reduce_ex__(self, protocol: SupportsIndex) -> tuple[Any, ...]:
        raise TypeError("a Secret cannot be pickled or copied")


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
        result = proc.run([*proc.GIT, "rev-parse", "--git-common-dir"], base)
    except proc.ToolError as exc:
        raise StateError(f"{exc}; set {STATE_DIR_ENV} to a directory") from exc
    if result.returncode != 0:
        raise StateError(
            f"{base} is not inside a Git clone, and maity keeps an agent's credential in its "
            "clone. Run maity from the clone the agent works in; without one, give this agent "
            f"a directory of its own and set it for every maity command, e.g. "
            f"`export {STATE_DIR_ENV}=~/.local/state/maity/<agent-handle>` (one directory per "
            "agent identity, never shared)"
        )
    common = Path(result.stdout.strip())
    if not common.is_absolute():
        common = base / common
    return common.resolve() / "maity"


def identity_dir(hub_host: str, handle: str) -> Path:
    """The state directory `maity join` gives an agent outside a Git clone (context/join.md):
    one per identity, `$XDG_STATE_HOME/maity/<hub host>/<handle>`, `~/.local/state` by
    default. Both parts come checked: `hub_host` from a parsed URL, `handle` by its pattern."""
    return _state_home() / "maity" / hub_host / handle


def _state_home() -> Path:
    """`$XDG_STATE_HOME`, else `~/.local/state`."""
    root = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(root).expanduser().resolve()


def _ensure_dir(path: Path) -> None:
    """Create the state directory 0700, or accept an existing one only if it is private already.

    A directory the user named (`MAITY_STATE_DIR`) is theirs: it is checked, never chmodded.
    """
    if path.is_dir():
        check_private(path)
        return
    path.mkdir(mode=0o700, parents=True)
    os.chmod(path, 0o700)  # mkdir's mode is masked by the umask; this one is not


def _atomic_write(path: Path, data: str, private_dir: bool = True) -> None:
    """Write `data` to `path` with mode 0600, never leaving a partly written file behind.

    `private_dir=False` accepts an existing directory as it is (a file without a secret in
    a directory the operator made); a missing one is still created 0700."""
    if private_dir or not path.parent.is_dir():
        _ensure_dir(path.parent)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    tmp = Path(tmp_name)  # mkstemp creates it 0600
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def check_private(path: Path, revoke: str = "revoke the session in the dashboard") -> None:
    """Refuse a file or directory others could reach, the way ssh refuses a loose private key.
    `revoke` is the way out when the file is not yours."""
    st = path.stat()
    if st.st_uid != os.getuid():
        raise StateError(f"{path} belongs to another user; refusing to use it")
    if st.st_mode & (stat.S_IRWXG | stat.S_IRWXO):
        mode = stat.S_IMODE(st.st_mode)
        fix = "700" if path.is_dir() else "600"
        raise StateError(
            f"{path} is accessible by group or others (mode {mode:04o}); "
            f"run `chmod {fix} {path}` if it is yours, or {revoke}"
        )


def prepare_for_join(path: Path) -> int | None:
    """Everything that could stop the credential from being written, checked before the
    join's single-use code is spent: the directory exists (created 0700 when missing), an
    empty one of this user's that is open to others is set to 0700 (`tighten_for_join`),
    it is private and ours (`check_private`), and writable. Returns the mode a tightened
    directory had, or None."""
    if not path.exists():
        path.mkdir(mode=0o700, parents=True)
        os.chmod(path, 0o700)
    was = tighten_for_join(path)
    check_private(path, revoke="give this agent a directory of its own")
    if not os.access(path, os.W_OK | os.X_OK):
        raise StateError(f"{path} is not writable; give this agent a directory it can write")
    return was


def rescue_credential(value: Secret) -> Path:
    """Where a credential goes when its directory refused it after the exchange: a new
    private directory under the home, so a spent join is never lost (the code works once)."""
    try:
        root = _state_home() / "maity"
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        rescue = Path(tempfile.mkdtemp(prefix="rescued-", dir=root))  # mkdtemp: 0700
    except OSError:  # the home itself may be what refused: the system's temp directory
        rescue = Path(tempfile.mkdtemp(prefix="maity-rescued-"))
    return write_credential(rescue, value)


def tighten_for_join(path: Path) -> int | None:
    """Before a join: an empty state directory of this user that is open to group or
    others is set to 0700, the mode it would have been created with. Returns the mode it
    had, or None when nothing changed. A directory with anything in it (a credential, or
    a home someone named by mistake), or another user's, is left to `check_private` and
    its refusal."""
    if not path.is_dir() or next(path.iterdir(), None) is not None:
        return None
    st = path.stat()
    if st.st_uid != os.getuid() or not st.st_mode & (stat.S_IRWXG | stat.S_IRWXO):
        return None
    os.chmod(path, 0o700)
    return stat.S_IMODE(st.st_mode)


def write_file(path: Path, text: str) -> Path:
    """Write a file 0600 that holds no secret (the runner's configuration); its directory
    is created 0700 when missing and taken as it is otherwise."""
    _atomic_write(path, text, private_dir=False)
    return path


def secret_once(path: Path) -> str:
    """A random secret kept in `path` (0600, its directory 0700): created on first use, by
    exactly one of two processes that race for it, and read back afterwards. Refused like a
    credential when others can reach it."""
    if not path.exists():
        _ensure_dir(path.parent)
        fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
        tmp = Path(tmp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(secrets.token_hex(32) + "\n")
                fh.flush()
                os.fsync(fh.fileno())
            try:
                os.link(tmp, path)  # fails when another process was first: theirs stands
            except FileExistsError:
                pass
        finally:
            tmp.unlink(missing_ok=True)
    check_private(path, "delete it, and a new one is made")
    value = path.read_text(encoding="utf-8").strip()
    if len(value) < 32:
        raise StateError(f"{path} does not hold a secret; delete it, and a new one is made")
    return value


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
    check_private(state_dir)
    check_private(path)
    value = path.read_text(encoding="utf-8").strip()
    if not value:
        raise StateError(f"{path} is empty; run `maity join` again")
    return Secret(value)


def load_state(state_dir: Path, name: str = STATE_FILE) -> dict[str, Any]:
    path = state_dir / name
    if not path.is_file():
        return {}
    check_private(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise StateError(f"{path} is not valid JSON: {exc.msg}") from exc
    if not isinstance(data, dict):
        raise StateError(f"{path} does not hold a JSON object")
    return data


def save_state(state_dir: Path, data: dict[str, Any], name: str = STATE_FILE) -> Path:
    path = state_dir / name
    _atomic_write(path, json.dumps(data, indent=2, sort_keys=True) + "\n")
    return path
