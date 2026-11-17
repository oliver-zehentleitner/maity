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
tokens, never shell strings, except the `pipe-pane` command (logcap), whose words are quoted.
"""

from __future__ import annotations

import hashlib
import os
import re
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


def is_wait(args: str) -> bool:
    """Whether a process's command line is a `maity wait`: a word naming the maity command,
    `maity` itself or a path ending in it (`python -m maity`, a venv's `bin/maity`), followed by
    `wait`, with maity's own `--for AGENT` (or `--for=AGENT`) allowed in between. A shell
    running such a line counts too: it holds the wait as long as it runs."""
    words = args.split()
    for i, word in enumerate(words):
        if os.path.basename(word) != "maity":
            continue
        rest = words[i + 1 :]
        if rest[:1] == ["--for"]:
            rest = rest[2:]
        elif rest[:1] and rest[0].startswith("--for="):
            rest = rest[1:]
        if rest[:1] == ["wait"]:
            return True
    return False


WAITING, WORKING, IDLE = "waiting", "working", "idle"


# A sandbox bridge as Claude Code's sandbox runtime builds it: its socket's own file name
# (never a directory above it) is claude-http- or claude-socks- and a hex id, and it
# forwards to a proxy on the loopback (the target word may carry options after the port,
# `TCP:localhost:3128,keepalive,…`, as the runtime builds it).
BRIDGE_SOCKET = re.compile(r"claude-(?:http|socks)-[0-9a-f]+\.sock")
BRIDGE_TARGET = re.compile(r"TCP:(?:localhost|127\.0\.0\.1):[0-9]+")


def is_helper(args: str) -> bool:
    """Whether a child of the harness is one of its own long-lived helpers rather than a tool
    it runs: Claude Code's sandbox on Linux keeps a `socat UNIX-LISTEN:…/claude-…sock` bridge
    per proxy for the whole session, at its prompt too. A socat of the agent's own, on any
    other socket, is a tool."""
    words = args.split()
    return (
        bool(words)
        and os.path.basename(words[0]) == "socat"
        and any(
            word.startswith("UNIX-LISTEN:")
            and BRIDGE_SOCKET.fullmatch(
                os.path.basename(word[len("UNIX-LISTEN:") :].split(",", 1)[0])
            )
            is not None
            for word in words[1:]
        )
        and any(BRIDGE_TARGET.fullmatch(word.split(",", 1)[0]) is not None for word in words[1:])
    )


def below(listing: str, root: int) -> str:
    """What runs below `root`, the pane's process (the harness), from the `pid ppid args`
    lines of `ps`: WAITING when a `maity wait` is among its descendants, WORKING when any
    other descendant runs (a tool the agent runs, however quiet, also one below a helper),
    IDLE when there is none but the harness's own helpers (`is_helper`) and their forks:
    the harness sits at its prompt."""
    if waits_below(listing, root):
        return WAITING
    if any(not is_helper(args) for args in _descendants(listing, root)):
        return WORKING
    return IDLE


def _descendants(listing: str, root: int) -> list[str]:
    """The command lines of every process below `root`, from the `pid ppid args` lines."""
    children: dict[int, list[tuple[int, str]]] = {}
    for line in listing.splitlines():
        parts = line.split(None, 2)
        if len(parts) < 2 or not parts[0].isdigit() or not parts[1].isdigit():
            continue
        children.setdefault(int(parts[1]), []).append(
            (int(parts[0]), parts[2] if len(parts) > 2 else "")
        )
    found: list[str] = []
    seen, queue = {root}, [root]
    while queue:
        for pid, args in children.get(queue.pop(), []):
            if pid not in seen:
                seen.add(pid)
                found.append(args)
                queue.append(pid)
    return found


def waits_below(listing: str, root: int) -> bool:
    """Whether a process below `root` (the pane's process) is a `maity wait`, from the
    `pid ppid args` lines of `ps`."""
    return any(is_wait(args) for args in _descendants(listing, root))


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
    log_keep: int = 10 * 1024 * 1024  # limits.log_keep_bytes: the most a pane log holds

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
            # The pane's output goes through logcap, which holds the log to `log_keep`.
            keep = [*self.as_user.runner_module("logcap"), str(log), str(self.log_keep)]
            self._check(self._tmux("pipe-pane", "-o", "-t", name, shlex.join(keep)))
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

    # --- the idle check (§15.14): what an interactive session shows -------------------------

    def attached(self, name: str) -> bool | None:
        """Whether a client is attached to the session, so a person may be at the pane;
        None when tmux could not say."""
        try:
            out = self._check(
                self._tmux("display-message", "-p", "-t", name, "#{session_attached}")
            )
        except TmuxError:
            return None
        value = out.strip()
        return int(value) > 0 if value.isdigit() else None

    def pane_digest(self, name: str) -> str | None:
        """A hash of what the session's pane shows now, to tell whether it changed; the text
        itself is never kept, logged or sent. None when tmux could not say."""
        try:
            out = self._check(self._tmux("capture-pane", "-p", "-t", name))
        except TmuxError:
            return None
        return hashlib.sha256(out.encode("utf-8", "replace")).hexdigest()

    def activity(self, session: Session) -> str | None:
        """What runs below the session's pane (`below`), read where the session runs; None
        when that could not be read."""
        if session.pid is None:
            return None
        try:
            # `-ww`: the whole command line; ps cuts it at the terminal's width otherwise,
            # and `maity wait` can sit past that behind a long path.
            done = self._exec(["ps", "-A", "-ww", "-o", "pid=,ppid=,args="])
        except (OSError, subprocess.TimeoutExpired):
            return None
        if done.returncode != 0:
            return None
        return below(done.stdout, session.pid)

    def type_text(self, name: str, text: str) -> None:
        """Type text into the session's pane without pressing Enter: `-l` sends it literally,
        so no word of it is read as a key name."""
        self._check(self._tmux("send-keys", "-t", name, "-l", text))

    def submit(self, name: str) -> None:
        """Press Enter in the session's pane."""
        self._check(self._tmux("send-keys", "-t", name, "Enter"))

    def type_line(self, name: str, line: str) -> None:
        """Type one line into the session's pane and press Enter."""
        self.type_text(name, line)
        self.submit(name)

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
