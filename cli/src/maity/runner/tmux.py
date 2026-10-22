"""The local backend: one tmux server for the agents, on the runner's own socket (runner design
§5.4, `single` layout).

A tmux server hands its own environment to every session, and `new-session -e` only adds to
it, so the server is started under `env -i` with a fixed environment: HOME, PATH =
`agent_path`, LANG, TERM. `SSH_AUTH_SOCK`, `MAITY_STATE_DIR`, the runner's own variables and
whatever the service manager set never reach an agent. The configuration file the server
reads sets `update-environment` empty (a client attaching later passes nothing on) and
`remain-on-exit` (an exited agent's status stays readable until the runner collects it).

Every session carries `@maity_placement` and `@maity_generation`, so a runner restart
rebuilds its picture from tmux, not from memory. Commands are argv lists built from validated
tokens, never shell strings, except the `pipe-pane` command, whose one path is quoted.
"""

from __future__ import annotations

import os
import shlex
import signal
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

PREFIX = "maity_"
CONF = 'set -g update-environment ""\nset -g remain-on-exit on\nset -g history-limit 5000\n'
FORMAT = (
    "#{session_name}\t#{pane_dead}\t#{pane_dead_status}\t#{pane_pid}\t"
    "#{@maity_placement}\t#{@maity_generation}"
)
TIMEOUT = 15.0

Runner = Callable[[Sequence[str]], "subprocess.CompletedProcess[str]"]


def _run(argv: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - argv lists from fixed templates and validated tokens
        list(argv),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=TIMEOUT,
        check=False,
    )


class TmuxError(Exception):
    pass


@dataclass(frozen=True)
class Session:
    name: str
    dead: bool
    exit_status: int | None
    pid: int | None
    placement: str | None
    generation: int | None


def session_name(project: str, clone: str) -> str:
    """`maity_<project>_<clone>`: the tokens are `[a-z0-9-]`, so `_` keeps two different
    pairs from ever giving one name (`ab` + `cd-ef` and `ab-cd` + `ef` would with `-`)."""
    return f"{PREFIX}{project}_{clone}"


@dataclass
class Tmux:
    socket: Path
    conf: Path
    home: str
    agent_path: str
    logs: Path
    run: Runner = _run

    def _tmux(self, *args: str) -> list[str]:
        return ["tmux", "-S", str(self.socket), *args]

    def _check(self, argv: Sequence[str]) -> str:
        try:
            done = self.run(argv)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise TmuxError(f"{argv[0]}: {exc}") from None
        if done.returncode != 0:
            raise TmuxError(f"`{' '.join(argv[3:5])}` failed: {done.stderr.strip()[:200]}")
        return done.stdout

    def environment(self) -> list[str]:
        """The server's whole environment: what every agent session starts with."""
        return [
            f"HOME={self.home}",
            f"PATH={self.agent_path}",
            "LANG=C.UTF-8",
            "TERM=xterm-256color",
        ]

    def sessions(self) -> dict[str, Session]:
        """Every pane of the server, keyed by session name; empty when no server runs."""
        try:
            done = self.run(self._tmux("list-panes", "-a", "-F", FORMAT))
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise TmuxError(f"tmux: {exc}") from None
        if done.returncode != 0:
            if "no server running" in done.stderr or "error connecting" in done.stderr:
                return {}
            raise TmuxError(f"tmux list-panes failed: {done.stderr.strip()[:200]}")
        found: dict[str, Session] = {}
        for line in done.stdout.splitlines():
            parts = line.split("\t")
            if len(parts) != 6 or not parts[0].startswith(PREFIX):
                continue
            name, dead, status, pid, placement, generation = parts
            found[name] = Session(
                name=name,
                dead=dead == "1",
                exit_status=int(status) if status.lstrip("-").isdigit() else None,
                pid=int(pid) if pid.isdigit() else None,
                placement=placement or None,
                generation=int(generation) if generation.isdigit() else None,
            )
        return found

    def start(
        self,
        name: str,
        cwd: Path,
        argv: Sequence[str],
        env: dict[str, str],
        placement: str,
        generation: int,
    ) -> None:
        self.conf.write_text(CONF, encoding="utf-8")
        log = self.logs / f"{placement}.log"
        self.logs.mkdir(mode=0o700, parents=True, exist_ok=True)
        log.touch(mode=0o600, exist_ok=True)
        extra = [arg for key, value in env.items() for arg in ("-e", f"{key}={value}")]
        command = [
            "env", "-i", *self.environment(),
            *self._tmux("-f", str(self.conf), "new-session", "-d", "-s", name, "-c", str(cwd)),
            *extra, "--", *argv,
        ]  # fmt: skip
        self._check(command)
        try:
            self._check(self._tmux("set-option", "-t", name, "@maity_placement", placement))
            self._check(self._tmux("set-option", "-t", name, "@maity_generation", str(generation)))
            self._check(
                self._tmux("pipe-pane", "-o", "-t", name, f"cat >> {shlex.quote(str(log))}")
            )
        except TmuxError:
            self.kill(name)  # an unlabelled session would run on, invisible to the runner
            raise

    def terminate(self, session: Session) -> None:
        """SIGTERM to the agent's process group; the session stays until `kill`. tmux makes
        the pane's process a session leader, so its pid is the group id; a pid that is not a
        group leader any more (reused) or that is the runner's own group is left alone."""
        pid = session.pid
        if pid is None or pid <= 1 or pid == os.getpgrp():
            return
        try:
            if os.getpgid(pid) != pid:
                return
            os.killpg(pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass

    def kill(self, name: str) -> None:
        try:
            self._check(self._tmux("kill-session", "-t", name))
        except TmuxError:
            pass  # already gone

    def environment_of(self, name: str) -> dict[str, str]:
        """The environment a session's processes get (for tests and `check`)."""
        out = self._check(self._tmux("show-environment", "-t", name))
        server = self._check(self._tmux("show-environment", "-g"))
        found: dict[str, str] = {}
        for line in (server + out).splitlines():
            if "=" in line and not line.startswith("-"):
                key, _, value = line.partition("=")
                found[key] = value
        return found
