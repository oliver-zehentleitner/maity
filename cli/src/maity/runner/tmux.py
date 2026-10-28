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
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from .asuser import SSH_UNREACHABLE, AsUser, Unreachable

PREFIX = "maity_"
CONF = 'set -g update-environment ""\nset -g remain-on-exit on\nset -g history-limit 5000\n'
FORMAT = (
    "#{session_name}\t#{pane_dead}\t#{pane_dead_status}\t#{pane_pid}\t"
    "#{@maity_placement}\t#{@maity_generation}\t#{window_index}.#{pane_index}"
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


def attach_words(socket: Path, name: str, as_user: AsUser) -> list[str]:
    """How the runner's owner attaches to a session: through sudo where the socket is the
    agents' user's."""
    attach = ["tmux", "-S", str(socket), "attach", "-t", name]
    return ["sudo", "-u", as_user.user, *attach] if as_user.user else attach


def attach_hint(socket: Path, name: str, as_user: AsUser) -> str:
    """`attach_words` as one line to paste, every word quoted."""
    return shlex.join(attach_words(socket, name, as_user))


def session_name(project: str, clone: str) -> str:
    """`maity_<project>_<clone>`, `project` the project's id (§15.5), which no rename changes:
    the tokens are `[a-z0-9-]`, so `_` keeps two different pairs from ever giving one name
    (`ab` + `cd-ef` and `ab-cd` + `ef` would with `-`). Sessions are found by their
    placement label, not by this name, so one started under an older name is still found."""
    return f"{PREFIX}{project}_{clone}"


@dataclass
class Tmux:
    socket: Path
    conf: Path
    home: str
    agent_path: str
    logs: Path
    run: Runner = _run
    as_user: AsUser = AsUser()  # the agents' user: the server is theirs (§7.6)

    def _tmux(self, *args: str) -> list[str]:
        return ["tmux", "-S", str(self.socket), *args]

    def _exec(self, argv: Sequence[str]) -> subprocess.CompletedProcess[str]:
        """`argv` where the agents' server lives: here, through sudo, or over ssh."""
        # A remote shell's own PATH may not be the one tmux was checked on (`agent_path`).
        env = None if self.as_user.here else {"PATH": self.agent_path}
        return self.run(self.as_user.argv(argv, env))

    def _check(self, argv: Sequence[str]) -> str:
        try:
            done = self._exec(argv)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise TmuxError(f"{argv[0]}: {exc}") from None
        if done.returncode != 0:
            words = list(argv[argv.index("tmux") + 3 :] if "tmux" in argv else argv)[:2]
            raise TmuxError(f"`tmux {' '.join(words)}` failed: {done.stderr.strip()[:200]}")
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
            done = self._exec(self._tmux("list-panes", "-a", "-F", FORMAT))
        except subprocess.TimeoutExpired:
            if not self.as_user.here:
                raise Unreachable("no answer within the timeout") from None
            raise TmuxError("tmux: no answer within the timeout") from None
        except OSError as exc:
            raise TmuxError(f"tmux: {exc}") from None
        if done.returncode == SSH_UNREACHABLE and not self.as_user.here:
            raise Unreachable(done.stderr.strip()[:200])
        if done.returncode != 0:
            if "no server running" in done.stderr or "error connecting" in done.stderr:
                return {}
            raise TmuxError(f"tmux list-panes failed: {done.stderr.strip()[:200]}")
        found: dict[str, Session] = {}
        for line in done.stdout.splitlines():
            parts = line.split("\t")
            if len(parts) != 7 or not parts[0].startswith(PREFIX) or parts[0] in found:
                continue  # the agent is the session's first pane; a pane added later is not
            name, dead, status, pid, placement, generation, _where = parts
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
        self.as_user.write(self.conf, CONF)
        log = self.logs / f"{placement}.log"
        self.as_user.mkdir(self.logs)
        if self.as_user.direct:
            log.touch(mode=0o600, exist_ok=True)
        extra = [arg for key, value in env.items() for arg in ("-e", f"{key}={value}")]
        command = [
            "env", "-i", *self.environment(),
            "tmux", "-S", str(self.socket), "-f", str(self.conf),
            "new-session", "-d", "-s", name, "-c", str(cwd),
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
        if pid is None or pid <= 1:
            return
        try:
            if self.as_user.here and (pid == os.getpgrp() or os.getpgid(pid) != pid):
                return  # a remote pid means nothing here; its host checks its own
            self.as_user.terminate(pid)
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
