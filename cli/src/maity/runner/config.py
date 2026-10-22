"""The runner's configuration (runner design §5.1; docs/api.md §15).

TOML, read with `tomllib`. Unknown
keys are refused, like unknown fields in the API, so a typo fails at `check` instead of
silently meaning a default. Keys left out take the defaults below; `~` is expanded in paths.
What a runner may do at all — projects, repositories, harnesses, how many agents — is this
file, and the hub cannot widen it. Every default is listed by `maity runner check --explain`.
"""

from __future__ import annotations

import os
import pwd
import re
import tomllib
import urllib.parse
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..hub import HubError, hub_base

DEFAULT_PATH = Path("~/.config/maity-runner/runner.toml")
DEFAULT_STATE_DIR = "~/.local/state/maity-runner"
DEFAULT_WORKSPACES = "~/maity-workspaces"

HARNESSES = ("claude-code", "codex", "opencode", "pi", "hermes", "kimi", "cline", "omp", "stub")
# No command allowlist in their own configuration (runner design §6.3): refused unless they
# run in a pod and the operator says so for each.
NOT_UNATTENDED = ("pi", "hermes", "kimi", "cline", "omp")
# Built but not offered: the maintainer decides on these when the runner goes into use.
NOT_OFFERED_YET = ("opencode",)
BINARIES = {"claude-code": "claude", "codex": "codex", "opencode": "opencode", "pi": "pi",
            "hermes": "hermes", "kimi": "kimi", "cline": "cline", "omp": "omp"}  # fmt: skip
MODES = ("interactive", "supervised")
SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{1,62}$")
# host/owner/name after normalise_repository(), or host/owner/* for a whole owner; no other glob
REPOSITORY = re.compile(r"^[a-z0-9.-]+(:[0-9]+)?/[A-Za-z0-9._-]+/([A-Za-z0-9._-]+|\*)$")


class ConfigError(Exception):
    """The configuration cannot be used; `problems` lists every reason, one per key."""

    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


@dataclass(frozen=True)
class Restart:
    initial: int = 10
    factor: float = 2.0
    max: int = 300
    crash_window: int = 1800
    crash_cap: int = 5
    quick_exit: int = 60


@dataclass(frozen=True)
class Limits:
    projects: tuple[str, ...]
    repositories: tuple[str, ...]
    max_agents: int = 4
    stop_grace_max: int = 120
    restart: Restart = field(default_factory=Restart)
    log_keep_bytes: int = 10 * 1024 * 1024
    require_local_approval: bool = False


@dataclass(frozen=True)
class Local:
    workspaces: Path
    tmux_socket: Path  # tmux -S; default <agent_files>/tmux.sock
    agent_files: Path = Path()  # tmux.conf, logs, harness files: the agents' side
    layout: str = "single"
    agent_user: str | None = None
    agent_path: str | None = None  # None: the service's own PATH at start
    memory_max: str | None = None
    cpu_quota: str | None = None


@dataclass(frozen=True)
class Harness:
    id: str
    modes: tuple[str, ...]
    default_mode: str
    models: tuple[str, ...] = ()
    default_model: str | None = None
    binary: str | None = None
    require_sandbox: bool = False
    env_file: Path | None = None
    stub_exit_code: int = 0
    stub_run_seconds: int = 30


@dataclass(frozen=True)
class RepositoryGrant:
    allow: tuple[str, ...] = ()
    network: tuple[str, ...] = ()


@dataclass(frozen=True)
class Config:
    path: Path
    hub_url: str
    state_dir: Path
    limits: Limits
    backend: str
    local: Local | None
    harnesses: dict[str, Harness]
    repositories: dict[str, RepositoryGrant]


# --- reading ---------------------------------------------------------------------------------


def path_of(given: str | None) -> Path:
    return Path(given or os.environ.get("MAITY_RUNNER_CONFIG") or DEFAULT_PATH).expanduser()


class _Reader:
    """Walks one table, refusing unknown keys and collecting every problem."""

    def __init__(self, data: Any, where: str, problems: list[str]) -> None:
        self.where = where
        self.problems = problems
        self.data: dict[str, Any] = data if isinstance(data, dict) else {}
        self.used: set[str] = set()
        if not isinstance(data, dict):
            problems.append(f"{where}: expected a table")

    def _name(self, key: str) -> str:
        return f"{self.where}.{key}" if self.where else key

    def get(
        self,
        key: str,
        kind: type | tuple[type, ...],
        default: Any = None,
        required: bool = False,
        check: Callable[[Any], str | None] | None = None,
    ) -> Any:
        self.used.add(key)
        if key not in self.data:
            if required:
                self.problems.append(f"{self._name(key)}: required")
            return default
        value = self.data[key]
        if isinstance(value, bool) and kind is not bool and bool not in _tuple(kind):
            self.problems.append(f"{self._name(key)}: expected {_kind_name(kind)}")
            return default
        if not isinstance(value, kind):
            self.problems.append(f"{self._name(key)}: expected {_kind_name(kind)}")
            return default
        if check is not None:
            reason = check(value)
            if reason:
                self.problems.append(f"{self._name(key)}: {reason}")
                return default
        return value

    def table(self, key: str, required: bool = False) -> _Reader | None:
        self.used.add(key)
        if key not in self.data:
            if required:
                self.problems.append(f"{self._name(key)}: required")
            return None
        return _Reader(self.data[key], self._name(key), self.problems)

    def done(self) -> None:
        for key in sorted(set(self.data) - self.used):
            self.problems.append(f"{self._name(key)}: unknown key")


def _tuple(kind: type | tuple[type, ...]) -> tuple[type, ...]:
    return kind if isinstance(kind, tuple) else (kind,)


def _kind_name(kind: type | tuple[type, ...]) -> str:
    names = {str: "a string", int: "an integer", float: "a number", bool: "true or false",
             list: "a list", dict: "a table"}  # fmt: skip
    return " or ".join(names.get(k, k.__name__) for k in _tuple(kind))


def _positive(value: Any) -> str | None:
    return None if value > 0 else "must be greater than 0"


def _strings(pattern: re.Pattern[str] | None = None, what: str = "") -> Callable[[Any], str | None]:
    def check(values: Any) -> str | None:
        if not all(isinstance(v, str) and v for v in values):
            return "expected a list of non-empty strings"
        if pattern is not None:
            bad = [v for v in values if not pattern.match(v)]
            if bad:
                return f"not {what}: {', '.join(repr(v) for v in bad)}"
        return None

    return check


def _one_of(*allowed: str) -> Callable[[Any], str | None]:
    return lambda v: None if v in allowed else f"one of {', '.join(allowed)}"


def _https_url(value: Any) -> str | None:
    """The rule `join` and `pair` apply: HTTPS, plain HTTP only on loopback, no user info."""
    try:
        hub_base(value)
    except HubError as exc:
        return str(exc)
    return None


def load(path: Path) -> Config:
    """The configuration at `path`; ConfigError listing every problem otherwise."""
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ConfigError([f"{path}: no such file; write it first (runner design §5.1)"]) from None
    except OSError as exc:
        raise ConfigError([f"{path}: cannot be read ({exc.strerror})"]) from None
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError([f"{path}: not valid TOML ({exc})"]) from None
    return parse(raw, path)


def parse(raw: dict[str, Any], path: Path) -> Config:
    problems: list[str] = []
    root = _Reader(raw, "", problems)

    hub = root.table("hub", required=True) or _Reader({}, "hub", [])
    hub_url = hub.get("url", str, required=True, check=_https_url) or ""
    state_dir = Path(hub.get("state_dir", str, DEFAULT_STATE_DIR)).expanduser()
    hub.done()

    limits_in = root.table("limits", required=True) or _Reader({}, "limits", [])
    projects = limits_in.get(
        "projects", list, [], required=True, check=_strings(SLUG, "a project slug")
    )
    repositories = limits_in.get("repositories", list, [], required=True, check=_repositories)
    restart = _RESTART
    restart_in = limits_in.table("restart")
    if restart_in is not None:
        restart = Restart(
            initial=restart_in.get("initial", int, _RESTART.initial, check=_positive),
            factor=float(restart_in.get("factor", (int, float), _RESTART.factor, check=_positive)),
            max=restart_in.get("max", int, _RESTART.max, check=_positive),
            crash_window=restart_in.get(
                "crash_window", int, _RESTART.crash_window, check=_positive
            ),
            crash_cap=restart_in.get("crash_cap", int, _RESTART.crash_cap, check=_positive),
            quick_exit=restart_in.get("quick_exit", int, _RESTART.quick_exit, check=_positive),
        )
        restart_in.done()
    limits = Limits(
        projects=tuple(projects),
        repositories=tuple(normalise_repository(r) for r in repositories),
        max_agents=limits_in.get("max_agents", int, _LIMITS.max_agents, check=_positive),
        stop_grace_max=limits_in.get("stop_grace_max", int, _LIMITS.stop_grace_max, check=_grace),
        restart=restart,
        log_keep_bytes=limits_in.get(
            "log_keep_bytes", int, _LIMITS.log_keep_bytes, check=_positive
        ),
        require_local_approval=limits_in.get("require_local_approval", bool, False),
    )
    limits_in.done()

    backend_in = root.table("backend") or _Reader({}, "backend", problems)
    kind = backend_in.get("kind", str, "local", check=_one_of("local", "ssh", "k8s"))
    local = None
    local_in = backend_in.table("local")
    if kind == "local":
        local_in = local_in or _Reader({}, "backend.local", problems)
        layout = local_in.get("layout", str, "single", check=_one_of("single", "agent_user"))
        agent_user = local_in.get("agent_user", str, None)
        if layout == "agent_user" and not agent_user:
            problems.append('backend.local.agent_user: required with layout = "agent_user"')
        # The agents' side lives where the agents' user can reach it: the runner's state
        # directory in the single layout, the agent user's home in the agent_user layout.
        agent_files = (
            home_of(agent_user) / ".maity-runner"
            if layout == "agent_user" and agent_user
            else state_dir
        )
        local = Local(
            workspaces=Path(local_in.get("workspaces", str, DEFAULT_WORKSPACES)).expanduser(),
            tmux_socket=Path(
                local_in.get("tmux_socket", str, str(agent_files / "tmux.sock"), check=_absolute)
            ).expanduser(),
            agent_files=agent_files,
            layout=layout,
            agent_user=agent_user,
            agent_path=local_in.get("agent_path", str, None),
            memory_max=local_in.get("memory_max", str, None),
            cpu_quota=local_in.get("cpu_quota", str, None),
        )
        local_in.done()
    # [backend.local] under another kind is not read, so its keys are not judged either
    for later, slice_ in (("ssh", "R7"), ("k8s", "phase 2")):
        later_in = backend_in.table(later)
        if later_in is not None or kind == later:
            problems.append(f"backend.{later}: not supported by this version yet ({slice_})")
    backend_in.done()

    harnesses: dict[str, Harness] = {}
    harness_in = root.table("harness", required=True)
    if harness_in is not None:
        for name in list(harness_in.data):
            table = harness_in.table(name)
            if name not in HARNESSES:
                problems.append(f"harness.{name}: unknown harness (one of {', '.join(HARNESSES)})")
                continue
            if table is None:
                continue
            harnesses[name] = _harness(name, table, problems)
            table.done()
        if not harness_in.data:
            problems.append("harness: name at least one harness")

    grants: dict[str, RepositoryGrant] = {}
    repos_in = root.table("repositories")
    if repos_in is not None:
        for name in list(repos_in.data):
            table = repos_in.table(name)
            if not REPOSITORY.match(normalise_repository(name)) or name.endswith("*"):
                problems.append(f"repositories.{name}: expected host/owner/name")
                continue
            if table is None:
                continue
            grants[normalise_repository(name)] = RepositoryGrant(
                allow=tuple(table.get("allow", list, [], check=_strings())),
                network=tuple(table.get("network", list, [], check=_strings())),
            )
            table.done()

    root.done()
    if problems:
        raise ConfigError(problems)
    return Config(path, hub_url, state_dir, limits, kind, local, harnesses, grants)


_RESTART = Restart()
_LIMITS = Limits(projects=(), repositories=())


def normalise_repository(value: str) -> str:
    """`host/owner/name` for a repository URL or config entry: scheme and user dropped,
    trailing `/` and `.git` stripped, host lowercased. Both the runner's `repositories` and the
    project's `repository.url` go through this, so `https://GitHub.com/o/n.git` and
    `github.com/o/n` are the same repository."""
    rest = value.strip()
    scheme = rest.find("://")
    if scheme != -1:
        rest = rest[scheme + 3 :]
    rest = rest.rstrip("/")
    if rest.endswith(".git"):
        rest = rest[: -len(".git")].rstrip("/")
    host, _, path = rest.partition("/")
    host = host.rpartition("@")[2].lower()
    return f"{host}/{path}" if path else host


_URL_NOISE = re.compile(r"[\s#?\\%]")


def repository_url_ok(url: str) -> bool:
    """A repository URL the runner may clone: https, or ssh with at most a user name, a host,
    and `owner/name`; nothing a URL parser and git could read differently (`#`, `?`, `\\`,
    percent escapes, whitespace) and no local or other transport (`file://`, `ext::`)."""
    if not url or _URL_NOISE.search(url):
        return False
    try:
        parts = urllib.parse.urlsplit(url)
        parts.port  # noqa: B018 - raises ValueError on a bad port
    except ValueError:
        return False
    if parts.scheme not in ("https", "ssh") or not parts.hostname or parts.password:
        return False
    if parts.username is not None and parts.scheme != "ssh":
        return False
    segments = [s for s in parts.path.split("/") if s]
    return len(segments) == 2


def repository_allowed(url: str, allowed: tuple[str, ...]) -> bool:
    """Whether the project's repository is one of `allowed` (normalised entries); never for
    a URL `repository_url_ok` refuses."""
    if not repository_url_ok(url):
        return False
    repo = normalise_repository(url)
    owner = repo.rpartition("/")[0]
    return any(entry == repo or entry == f"{owner}/*" for entry in allowed)


def _repositories(values: Any) -> str | None:
    if not all(isinstance(v, str) and v for v in values):
        return "expected a list of non-empty strings"
    bad = [v for v in values if not REPOSITORY.match(normalise_repository(v))]
    if bad:
        return "expected host/owner/name or host/owner/* (no other wildcard): " + ", ".join(
            repr(v) for v in bad
        )
    return None


def _absolute(value: Any) -> str | None:
    return None if Path(value).expanduser().is_absolute() else "expected an absolute path"


def home_of(user: str) -> Path:
    """A user's home directory; `/home/<user>` when this host does not know the user (the
    check reports that separately)."""
    try:
        return Path(pwd.getpwnam(user).pw_dir)
    except KeyError:
        return Path("/home") / user


def unsupported(cfg: Config) -> list[str]:
    """What the configuration asks for that this version does not do yet. `check` reports
    each as an error and `serve` refuses to start, rather than running agents with less
    isolation or fewer limits than the operator wrote down."""
    found: list[str] = []
    if cfg.local is not None:
        if cfg.local.memory_max is not None:
            found.append("backend.local.memory_max is not enforced yet; remove it or wait for it")
        if cfg.local.cpu_quota is not None:
            found.append("backend.local.cpu_quota is not enforced yet; remove it or wait for it")
    for harness in cfg.harnesses.values():
        if harness.env_file is not None:
            found.append(f"harness.{harness.id}.env_file is not passed on yet (R5)")
    return found


def _grace(value: Any) -> str | None:
    return None if 0 <= value <= 900 else "0 to 900 (the hub's stop_grace_seconds range)"


def _harness(name: str, table: _Reader, problems: list[str]) -> Harness:
    where = f"harness.{name}"
    if name in NOT_UNATTENDED:
        problems.append(
            f"{where}: has no command allowlist of its own and cannot run unattended here "
            "(runner design §6.3)"
        )
    elif name in NOT_OFFERED_YET:
        problems.append(
            f"{where}: not offered yet; for now the runner runs claude-code and codex (and stub)"
        )
    modes = tuple(
        table.get(
            "modes",
            list,
            ["supervised"],
            check=_strings(re.compile("^(interactive|supervised)$"), "a mode"),
        )
    )
    default_mode = table.get("default_mode", str, modes[0] if modes else "supervised")
    if modes and default_mode not in modes:
        problems.append(f"{where}.default_mode: must be one of its modes")
    models = tuple(table.get("models", list, [], check=_strings()))
    if not modes and "modes" in table.data:
        problems.append(f"{where}.modes: name at least one mode")
    default_model = table.get("default_model", str, models[0] if models else None)
    if default_model is not None and default_model not in models:
        problems.append(f"{where}.default_model: must be one of its models")
    env_file = table.get("env_file", str, None)
    harness = Harness(
        id=name,
        modes=modes,
        default_mode=default_mode,
        models=models,
        default_model=default_model,
        binary=None if name == "stub" else table.get("binary", str, BINARIES.get(name)),
        require_sandbox=table.get("require_sandbox", bool, False),
        env_file=Path(env_file).expanduser() if env_file else None,
    )
    if name == "stub":
        return Harness(
            **{**harness.__dict__,
               "stub_exit_code": table.get("exit_code", int, 0),
               "stub_run_seconds": table.get("run_seconds", int, 30, check=_positive)}
        )  # fmt: skip
    return harness
