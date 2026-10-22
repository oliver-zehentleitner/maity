"""`maity runner pair` and `maity runner check` (runner design §11, slice R1)."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import stat
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .. import hub, proc, state
from . import config

STATE_FILE = "runner.json"
REVOKE = "revoke the runner in the dashboard"
VERSION_TIMEOUT = 10.0
HEALTH_TIMEOUT = 10.0


class Refused(Exception):
    """The command is refused before anything is sent; exits 2 like a usage error."""


# --- pair ------------------------------------------------------------------------------------


def _code(args: argparse.Namespace) -> str:
    if args.code_file is not None:
        source = sys.stdin if args.code_file == "-" else None
        text = source.read() if source else Path(args.code_file).read_text(encoding="utf-8")
    else:
        text = args.code or ""
    code = text.strip()
    if not code:
        raise Refused("the pairing code is empty")
    return code


def _hub_table(path: Path) -> tuple[str, Path]:
    """`hub.url` and `hub.state_dir` of an existing configuration; nothing else is read, so a
    configuration still missing its limits can be paired again after a revocation."""
    tomllib = config.require_tomllib()
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise config.ConfigError([f"{path}: not valid TOML ({exc})"]) from None
    table = raw.get("hub")
    url = table.get("url") if isinstance(table, dict) else None
    if not isinstance(url, str) or not url:
        raise config.ConfigError([f"{path}: hub.url: required"])
    state_dir = table.get("state_dir", config.DEFAULT_STATE_DIR) if isinstance(table, dict) else ""
    if not isinstance(state_dir, str) or not state_dir:
        raise config.ConfigError([f"{path}: hub.state_dir: expected a string"])
    return url, Path(state_dir).expanduser()


def starter_config(base: str) -> str:
    """What `pair` writes when no configuration exists: the hub, and nothing it could guess."""
    return (
        "# Written by `maity runner pair`. Add [limits] and at least one [harness.<id>],\n"
        "# then run `maity runner check` (every default: `maity runner check --explain`).\n"
        "[hub]\n"
        f"url = {json.dumps(base)}\n"
        f"state_dir = {json.dumps(config.DEFAULT_STATE_DIR)}\n"
    )


def cmd_pair(args: argparse.Namespace) -> int:
    config.require_tomllib()
    base = hub.hub_base(args.url)
    token = hub.pair_token(args.url)
    code = _code(args)
    path = config.path_of(args.config)
    created = False
    if path.exists():
        configured, state_dir = _hub_table(path)
        if hub.hub_base(configured) != base:
            raise Refused(
                f"{path} is the configuration of the runner for {hub.safe_url(configured)}; "
                "name a new one with --config to pair with another hub"
            )
    else:
        state_dir = Path(config.DEFAULT_STATE_DIR).expanduser()
        created = True
    _preflight(state_dir, path if created else None)
    result = hub.pair_exchange(base, token, code)
    hub_url = hub.accept_hub(args.url, result.hub)  # before anything is kept
    # The credential first: once the exchange is done, the enrollment is spent, and the
    # credential is the one thing that cannot be had again.
    stored = state.write_credential(state_dir, result.credential)
    state.save_state(
        state_dir,
        {
            "hub": hub_url,
            "runner_id": result.runner_id,
            "credential_id": result.credential_id,
        },
        name=STATE_FILE,
    )
    attached = ", ".join(result.attached) or "none yet"
    print(
        f"paired as runner {result.runner_id}; attached to: {attached}; credential "
        f"{result.credential_id} stored in {stored} (mode 0600, not printed)",
        file=sys.stderr,
    )
    if created:
        try:
            state.write_file(path, starter_config(hub_url))
        except OSError as exc:
            print(
                f"could not write {path} ({exc.strerror}); the credential is stored. Write the "
                f"configuration by hand, starting with:\n{starter_config(hub_url)}",
                file=sys.stderr,
            )
            return 1
        print(f"wrote {path}; add [limits] and a [harness.<id>] to it", file=sys.stderr)
    print("next: `maity runner check`", file=sys.stderr)
    return 0


def _writable(path: Path) -> bool:
    """Whether `path` can be written, or created below its nearest existing parent."""
    existing = path if path.exists() else _existing_parent(path)
    return existing.is_dir() and os.access(existing, os.W_OK | os.X_OK)


def _preflight(state_dir: Path, new_config: Path | None) -> None:
    """Everything that would make storing the result fail, checked before the code is
    spent: the exchange is single use, and its credential exists nowhere else."""
    if state.has_credential(state_dir):
        raise Refused(
            f"{state_dir} already holds a runner credential. To pair again, move that file "
            "away first (a re-pair revokes it at the exchange); to replace the runner, "
            f"{REVOKE}"
        )
    if state_dir.exists():
        try:
            state.check_private(state_dir, REVOKE)
        except state.StateError as exc:
            raise Refused(str(exc)) from None
    if not _writable(state_dir):
        raise Refused(f"state_dir {state_dir} cannot be created or written by this user")
    if new_config is not None and not _writable(new_config.parent):
        raise Refused(f"{new_config.parent} cannot be created or written by this user")


# --- check -----------------------------------------------------------------------------------


@dataclass
class Report:
    lines: list[tuple[str, str]] = field(default_factory=list)

    def ok(self, text: str) -> None:
        self.lines.append(("ok", text))

    def warn(self, text: str) -> None:
        self.lines.append(("warn", text))

    def error(self, text: str) -> None:
        self.lines.append(("error", text))

    @property
    def failed(self) -> bool:
        return any(level == "error" for level, _ in self.lines)

    def print(self) -> None:
        for level, text in self.lines:
            print(f"{level:5}  {text}")


DEFAULTS = (
    ("hub.state_dir", config.DEFAULT_STATE_DIR),
    ("limits.max_agents", "4"),
    ("limits.stop_grace_max", "120 (seconds; caps a placement's stop_grace_seconds)"),
    ("limits.restart", "at most 5 exits in 1800 s; backoff from 10 s, factor 2, cap 300 s; "
                       "an exit within 60 s counts as a crash"),  # fmt: skip
    ("limits.log_keep_bytes", "10 MiB per placement"),
    ("limits.require_local_approval", "false"),
    ("backend.kind", "local"),
    ("backend.local.workspaces", config.DEFAULT_WORKSPACES),
    ("backend.local.tmux_socket", "<state_dir>/tmux.sock"),
    ("backend.local.layout", "single"),
    ("backend.local.agent_path", "the service's own PATH at start"),
    ("backend.local.memory_max, cpu_quota", "unset (no limit)"),
    ("harness.<id>.modes", '["supervised"]; default_mode: the first'),
    ("harness.<id>.binary", "the harness's usual command, resolved on agent_path"),
    ("harness.<id>.require_sandbox", "false"),
    ("harness.<id>.env_file", "unset"),
)

EXPLAIN = (
    "Required: hub.url, limits.projects, limits.repositories, one [harness.<id>].\n"
    'limits.repositories: "host/owner/name" or "host/owner/*"; a scheme, a trailing / and\n'
    ".git are dropped and the host lowercased, the same as for the project's repository.\n"
    "Unknown keys are refused. Defaults:\n"
)


def explain() -> str:
    width = max(len(key) for key, _ in DEFAULTS)
    return EXPLAIN + "".join(f"  {key:<{width}}  {value}\n" for key, value in DEFAULTS)


def _private(report: Report, path: Path, what: str) -> None:
    try:
        state.check_private(path, REVOKE)
    except state.StateError as exc:
        report.error(str(exc))
    else:
        report.ok(f"{what} {path} is private")


def _check_config_file(report: Report, path: Path) -> None:
    """The configuration decides what agents may touch: nobody else may change it."""
    st = path.stat()
    if st.st_uid not in (os.getuid(), 0):
        report.warn(f"{path} belongs to another user, who can change what this runner may do")
    if st.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        report.warn(
            f"{path} is writable by group or others, who can change what this runner may do; "
            f"run `chmod go-w {path}`"
        )


def _check_state(report: Report, cfg: config.Config) -> None:
    directory = cfg.state_dir
    if not directory.is_dir():
        report.error(f"state_dir {directory} does not exist; run `maity runner pair` first")
        return
    _private(report, directory, "state_dir")
    if state.has_credential(directory):
        _private(report, state.credential_path(directory), "credential")
    else:
        report.error(f"no runner credential in {directory}; run `maity runner pair` first")


def _check_local(report: Report, local: config.Local) -> None:
    if shutil.which("tmux") is None:
        report.error("tmux is not installed; the local backend runs every agent in tmux")
    else:
        report.ok("tmux found")
    workspaces = local.workspaces
    existing = workspaces if workspaces.exists() else _existing_parent(workspaces)
    if not existing.is_dir() or not os.access(existing, os.W_OK | os.X_OK):
        report.error(f"workspaces {workspaces} cannot be created or written by this user")
    else:
        report.ok(f"workspaces {workspaces}")
    if local.layout == "agent_user":
        report.error('layout = "agent_user" is not supported by this version yet (R6)')


def _existing_parent(path: Path) -> Path:
    while not path.exists() and path != path.parent:
        path = path.parent
    return path


def _version(binary: str) -> str | None:
    try:
        done = proc.run([binary, "--version"], cwd=Path.home(), timeout=VERSION_TIMEOUT)
    except proc.ToolError:
        return None
    first = (done.stdout or done.stderr).strip().splitlines()
    return first[0][:80] if done.returncode == 0 and first else None


def _check_harness(report: Report, harness: config.Harness, agent_path: str) -> None:
    if harness.id == "stub":
        report.ok("harness stub (test adapter)")
        return
    binary = shutil.which(harness.binary or "", path=agent_path)
    if binary is None:
        report.error(f"harness {harness.id}: `{harness.binary}` not found on {agent_path}")
        return
    version = _version(binary)
    report.ok(f"harness {harness.id}: {binary} ({version or 'version unknown'})")
    if harness.env_file is not None:
        if harness.env_file.is_file():
            _private(report, harness.env_file, f"harness {harness.id} env_file")
        else:
            report.error(f"harness {harness.id}: env_file {harness.env_file} does not exist")
    if harness.id == "claude-code":
        _check_claude_code(report, harness)


def _check_claude_code(report: Report, harness: config.Harness) -> None:
    if sys.platform.startswith("linux"):
        missing = [tool for tool in ("bwrap", "socat") if shutil.which(tool) is None]
        if missing:
            line = f"harness claude-code: no OS sandbox ({', '.join(missing)} missing)"
            (report.error if harness.require_sandbox else report.warn)(line)
    settings = _json_file(Path.home() / ".claude" / "settings.json")
    if settings is None:
        return
    permissions = settings.get("permissions")
    allow = permissions.get("allow") if isinstance(permissions, dict) else None
    if isinstance(allow, list) and allow:
        report.warn(
            f"harness claude-code: ~/.claude/settings.json allows {len(allow)} rule(s) of its "
            "own; every agent this runner starts inherits them"
        )
    if settings.get("hooks"):
        report.warn("harness claude-code: ~/.claude/settings.json defines hooks; agents run them")


def _json_file(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _check_hub(report: Report, cfg: config.Config) -> None:
    try:
        base = hub.hub_base(cfg.hub_url)
        hub.get_text(f"{base}{hub.API}/health", timeout=HEALTH_TIMEOUT)
    except hub.HubError as exc:
        report.error(f"hub: {exc}")
        return
    report.ok(f"hub {base} answers")
    paired = state.load_state(cfg.state_dir, name=STATE_FILE) if cfg.state_dir.is_dir() else {}
    if paired.get("hub") and paired["hub"] != base:
        report.error(
            f"the credential in {cfg.state_dir} was issued by {hub.safe_url(paired['hub'])}, "
            f"not by {base}"
        )


def cmd_check(args: argparse.Namespace) -> int:
    config.require_tomllib()  # all of `maity runner` refuses on 3.10, --explain too
    if args.explain:
        print(explain(), end="")
        return 0
    path = config.path_of(args.config)
    report = Report()
    try:
        cfg = config.load(path)
    except config.ConfigError as exc:
        for problem in exc.problems:
            report.error(problem)
        report.print()
        return 1
    report.ok(f"configuration {path}")
    _check_config_file(report, path)
    _check_state(report, cfg)
    if cfg.local is not None:
        _check_local(report, cfg.local)
    agent_path = (cfg.local.agent_path if cfg.local else None) or os.environ.get("PATH", "")
    for harness in cfg.harnesses.values():
        _check_harness(report, harness, agent_path)
    if not args.offline:
        _check_hub(report, cfg)
    report.print()
    return 1 if report.failed else 0


# --- parser ----------------------------------------------------------------------------------


def add_parser(sub: Any, fmt: type[argparse.HelpFormatter]) -> None:
    p = sub.add_parser(
        "runner",
        help="run agents on this machine for a hub (Python 3.11+)",
        description="The runner service: pair this machine with a hub, check its configuration, "
        "and start or stop agents on placements. Reads its own configuration "
        f"({config.DEFAULT_PATH}, or --config), never MAITY_STATE_DIR.",
        formatter_class=fmt,
    )
    rsub = p.add_subparsers(dest="runner_command", metavar="<action>", required=True)

    r = rsub.add_parser(
        "pair",
        help="exchange a pairing code for the runner's credential",
        description="Exchange the single-use pairing code for the runner's credential and store "
        "it under state_dir (0600, never printed). Without a configuration, writes one with the "
        "hub and the default state_dir. A configuration for another hub is refused.",
        formatter_class=fmt,
    )
    r.add_argument("url", help="the pairing URL (https://<hub>/r/<token>)")
    code = r.add_mutually_exclusive_group(required=True)
    code.add_argument("--code", help="the single-use pairing code")
    code.add_argument("--code-file", help="read the code from this file, or stdin with -")
    r.add_argument("--config", help=f"configuration file (default {config.DEFAULT_PATH})")
    r.set_defaults(handler=cmd_pair)

    r = rsub.add_parser(
        "check",
        help="validate the configuration and this machine; exits 1 on any error",
        description="Validate the configuration, the state directory, tmux and the workspaces, "
        "each harness's binary and version, sandbox prerequisites and the harness settings "
        "agents would inherit, then GET /health on the hub. Nothing else is sent.",
        formatter_class=fmt,
    )
    r.add_argument("--config", help=f"configuration file (default {config.DEFAULT_PATH})")
    r.add_argument("--explain", action="store_true", help="print every key's default and stop")
    r.add_argument("--offline", action="store_true", help="do not contact the hub")
    r.set_defaults(handler=cmd_check)
