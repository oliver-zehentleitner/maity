"""The runner's watch, its pure parts (docs/api.md §15.14 "The runner's watch", §15.7 "A
finding" and "The runner's log lines"; card tsk-bzmd0avm4yhb).

The hub supplies the facts on each placement the runner reads (`session`); the runner sees
the process, its exit code and the pane. This module turns them into a trigger, a cause and a
`finding`, and builds the finding's `log` from the runner's own notes about the placement. It
reads no file, runs no process and calls no hub: the supervisor gathers the signals and acts.

Times here are seconds since the epoch. "Hub time" is the runner's clock plus the offset it
measured against the hub's `server_time` (§15.8); every comparison with a time the hub sent
is made in hub time.

The closed lists are the hub's (hub/src/maity_hub/placements.py, `FINDING_CAUSES`,
`PANE_CODES`, `SIGNAL_VALUES`, `check_finding`); a value outside them makes the hub refuse the
whole report, so the builders here refuse it first (ValueError: a bug in the caller).
"""

from __future__ import annotations

import re
import threading
from collections import deque
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from .. import hub, sign

# --- the closed lists (§15.7) ----------------------------------------------------------------

CAUSES = (
    "harness_exited",
    "not_waiting",
    "wait_deaf",
    "never_joined",
    "usage_limit",
    "login_invalid",
    "pickup_refused",
    "unknown",
)
# The causes whose reaction is a restart: only they count toward `auto_restarts` (§15.14,
# "The second failure stops").
RESTART_CAUSES = ("harness_exited", "wait_deaf", "never_joined", "unknown")
PANE_CODES = ("usage_limit", "login_prompt")
PROCESS = ("alive", "gone")
BELOW = ("waiting", "working", "idle", "unknown")
LOGIN = ("ok", "needed", "unknown")
PANE_MATCH_MAX = 8

# The triggers, which are also the `hung` details the watch reports (§15.7).
NOT_LISTENING = "not_listening"
NEVER_JOINED = "never_joined"

# `finding.log` (§15.7): at most 200 entries, each line 1 to 1024 bytes of printable ASCII,
# 24 KiB together; a longer line is cut at 1021 bytes and ends with `...`.
LOG_LINES_MAX = 200
LOG_LINE_BYTES = 1024
LOG_TOTAL_BYTES = 24 * 1024
CUT_AT = LOG_LINE_BYTES - 3
# What of a line the scrub reads at most. Longer than any line that is sent, so a secret the
# scrub has to see always lies within it; it only bounds the work on a runaway line.
SCRUB_INPUT_MAX = 4 * LOG_LINE_BYTES

# The form §1.1 gives every timestamp: `2026-11-20T20:26:00Z`, whole seconds, `Z`.
WIRE_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
WIRE_TIMESTAMP = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z")


def stamp(moment: float) -> str:
    """`moment` in the wire form of §1.1 (whole seconds, `Z`), as the hub requires of a
    finding's times."""
    return datetime.fromtimestamp(moment, tz=UTC).strftime(WIRE_FORMAT)


def parse_stamp(value: Any) -> float | None:
    """A timestamp the hub sent, in the wire form only; None for anything else (an offset, a
    fraction, an epoch, a date that does not exist)."""
    if not isinstance(value, str) or not WIRE_TIMESTAMP.fullmatch(value):
        return None
    try:
        return datetime.strptime(value, WIRE_FORMAT).replace(tzinfo=UTC).timestamp()
    except ValueError:
        return None


def offset_from(server_time: Any, received_at: float) -> float | None:
    """The hub's clock minus the runner's, from a `server_time` (§15.8) the runner received at
    `received_at` on its own clock; None when `server_time` is not a wire-form timestamp."""
    hub_at = parse_stamp(server_time)
    return None if hub_at is None else hub_at - received_at


# --- what the hub says about the agent (§15.8 `session`) -------------------------------------


@dataclass(frozen=True)
class SessionFacts:
    """A placement's `session` as the runner reads it, its times in hub time."""

    started_at: float | None
    not_listening_since: float | None
    paused: bool
    dormant: bool

    @property
    def resting(self) -> bool:
        """Someone decided this agent should rest: the watch does nothing for it (§15.14)."""
        return self.paused or self.dormant


def takes_finding(placement: dict[str, Any]) -> bool:
    """Whether the hub takes `finding`: its placements carry the `session` key, `null`
    included (§15.8). An older hub refuses a report with a field it does not know."""
    return "session" in placement


def session_facts(placement: dict[str, Any]) -> SessionFacts | None:
    """The placement's `session`; None for a foreign placement (`session: null`), a hub
    without it, or a value not in the contract's form, for which the watch has no trigger."""
    raw = placement.get("session")
    if not isinstance(raw, dict):
        return None
    paused, dormant = raw.get("paused"), raw.get("dormant")
    if not isinstance(paused, bool) or not isinstance(dormant, bool):
        return None
    times: list[float | None] = []
    for key in ("started_at", "not_listening_since"):
        value = raw.get(key)
        parsed = parse_stamp(value)
        if value is not None and parsed is None:
            return None
        times.append(parsed)
    return SessionFacts(times[0], times[1], paused, dormant)


def trigger(
    facts: SessionFacts | None,
    *,
    interactive: bool,
    run_started: float | None,
    hub_now: float,
    grace: float,
    join_within: float,
) -> str | None:
    """Which trigger holds now (§15.14, "When it looks"), or None. All times in hub time,
    `grace` and `join_within` in seconds; `run_started` is when the runner started the harness
    for this run, None when it does not know (a session it adopted).

    - `never_joined`: `join_within` has passed since the run started and no session of the
      placement's credential started since then. It goes first when both hold: an episode
      that began before this run belongs to an earlier session, and that no session started
      since is the truer finding.
    - `not_listening`: interactive only, the session has been not listening for `grace`. The
      grace counts from the later of the episode's start and this run's start (the runner's
      decision, cli/context/runner.md): right after a restart the hub may still report the
      earlier session's episode, which would otherwise trigger again at once."""
    if facts is None or facts.resting:
        return None
    if (
        run_started is not None
        and hub_now - run_started >= join_within
        and (facts.started_at is None or facts.started_at < run_started)
    ):
        return NEVER_JOINED
    since = facts.not_listening_since
    if interactive and since is not None:
        if run_started is not None:
            since = max(since, run_started)
        if hub_now - since >= grace:
            return NOT_LISTENING
    return None


# --- the pane's signatures (§15.7, the pane codes) ------------------------------------------


@dataclass(frozen=True)
class PaneSignature:
    """A text that shows a pane code in one harness's pane, verified on a real run of each of
    `versions`."""

    harness: str
    versions: tuple[str, ...]
    code: str
    text: str


# None verified yet (the lead's ruling on tsk-bzmd0avm4yhb): a code is matched only on a
# signature verified on a real run of that harness and version, and a harness without one
# matches nothing. A pane match is a signal only; it never decides a cause.
PANE_SIGNATURES: tuple[PaneSignature, ...] = ()


def _signatures_for(
    harness: str, version: str | None, signatures: Sequence[PaneSignature]
) -> list[PaneSignature]:
    if version is None:  # a version nobody verified a signature on
        return []
    return [s for s in signatures if s.harness == harness and version in s.versions]


def pane_texts(
    harness: str, version: str | None, signatures: Sequence[PaneSignature] = PANE_SIGNATURES
) -> tuple[str, ...]:
    """The texts to look for in this harness's pane at this version (`Tmux.pane_has`)."""
    return tuple(dict.fromkeys(s.text for s in _signatures_for(harness, version, signatures)))


def pane_match(
    harness: str,
    version: str | None,
    shown: Iterable[str] | None,
    signatures: Sequence[PaneSignature] = PANE_SIGNATURES,
) -> list[str]:
    """The pane codes the shown texts stand for, each once, in the contract's order; `[]`
    when the pane could not be read (`shown` None) or nothing matched."""
    if shown is None:
        return []
    seen = set(shown)
    codes = {s.code for s in _signatures_for(harness, version, signatures) if s.text in seen}
    return [code for code in PANE_CODES if code in codes]


# --- the signals, the cause and the finding ---------------------------------------------------


def _exit_code_ok(value: Any) -> bool:
    return value is None or (
        isinstance(value, int) and not isinstance(value, bool) and -(2**31) <= value < 2**31
    )


def signals(
    *,
    process: str,
    exit_code: int | None,
    below: str,
    pane_match: Sequence[str],
    login: str,
    pickup_code: str | None,
) -> dict[str, Any]:
    """`finding.signals` (§15.7), every key present. A process that is `alive` has no exit
    code; one that is `gone` has nothing below it (`unknown`). ValueError for a value outside
    the hub's lists or forms."""
    if process not in PROCESS:
        raise ValueError(f"process: {process!r}")
    if below not in BELOW:
        raise ValueError(f"below: {below!r}")
    if login not in LOGIN:
        raise ValueError(f"login: {login!r}")
    if not _exit_code_ok(exit_code):
        raise ValueError(f"exit_code: {exit_code!r}")
    codes = list(pane_match)
    if (
        len(codes) > PANE_MATCH_MAX
        or len(set(codes)) != len(codes)
        or any(code not in PANE_CODES for code in codes)
    ):
        raise ValueError(f"pane_match: {codes!r}")
    if pickup_code is not None and not (
        isinstance(pickup_code, str) and hub.ERROR_CODE.fullmatch(pickup_code)
    ):
        raise ValueError("pickup_code: not in the code form")
    return {
        "process": process,
        "exit_code": exit_code if process == "gone" else None,
        "below": below if process == "alive" else "unknown",
        "pane_match": codes,
        "login": login,
        "pickup_code": pickup_code,
    }


def diagnose(
    trigger_: str,
    found: dict[str, Any],
    *,
    limit_exit: bool,
    quiet_for: float | None,
    tool_call_max: float,
) -> str | None:
    """The first cause that fits (§15.14, "The diagnosis"), or None while a process other
    than `maity wait` runs below the harness and the session has been not listening for less
    than `tool_call_max` seconds (`quiet_for`, from the episode's start): that is work, and
    the runner looks again at its next pass.

    `limit_exit` is the harness adapter's recognition of a limit exit (the supervised loop's
    exit for its provider's limit); a pane match decides neither `usage_limit` nor
    `login_invalid`, and a harness without a login probe (`login: unknown`) never gets
    `login_invalid`."""
    if found["login"] == "needed":
        return "login_invalid"
    if limit_exit:
        return "usage_limit"
    if found["process"] == "gone":
        return "harness_exited"
    if trigger_ == NOT_LISTENING:
        below = found["below"]
        if below == "waiting":
            return "wait_deaf"
        if below == "idle":
            return "not_waiting"
        if below == "working":
            return "unknown" if quiet_for is not None and quiet_for >= tool_call_max else None
        return "unknown"
    if trigger_ == NEVER_JOINED:
        return "never_joined"
    return "unknown"


def finding(
    cause: str, seen_at: float, found: dict[str, Any], log: Sequence[dict[str, str]] = ()
) -> dict[str, Any]:
    """`finding` for a status report (§15.7): `seen_at` in hub time, `found` from `signals`,
    `log` from `log_entries` and left out when it holds no line."""
    if cause not in CAUSES:
        raise ValueError(f"cause: {cause!r}")
    built: dict[str, Any] = {"cause": cause, "seen_at": stamp(seen_at), "signals": dict(found)}
    if log:
        built["log"] = [dict(entry) for entry in log]
    return built


def may_restart(
    restarts: Sequence[float], now: float, window: float, auto_restarts: int
) -> tuple[bool, list[float]]:
    """Whether the watch may restart once more (§15.14, "The second failure stops"): fewer
    than `auto_restarts` of its restarts in the last `window` seconds. Also the restarts still
    in the window, the list the runner keeps."""
    recent = [at for at in restarts if now - at < window]
    return len(recent) < auto_restarts, recent


def hung_report(trigger_: str, held: bool) -> tuple[str, str, str]:
    """The state, reason and detail of a restart cause's report: `exited` when the runner
    starts it again, `failed` when the cap holds it (§15.14)."""
    return ("failed" if held else "exited", "hung", trigger_)


# --- the runner's notes and `finding.log` -----------------------------------------------------


class Notes:
    """The runner's own lines about each placement, the newest LOG_LINES_MAX of each, in
    memory only (the lead's ruling: lost when the runner restarts). Only lines the runner
    writes here can reach `finding.log`; every line starts with its placement's id."""

    def __init__(self, keep: int = LOG_LINES_MAX) -> None:
        self._keep = keep
        self._lock = threading.Lock()
        self._lines: dict[str, deque[tuple[float, str]]] = {}

    def add(self, placement: str, at: float, text: str) -> str:
        """Keep `<placement>: <text>`, written at `at`; returns the line for the service log."""
        line = f"{placement}: {text}"
        with self._lock:
            self._lines.setdefault(placement, deque(maxlen=self._keep)).append((at, line))
        return line

    def entries(self, placement: str) -> list[tuple[float, str]]:
        with self._lock:
            return list(self._lines.get(placement, ()))

    def forget(self, placement: str) -> None:
        with self._lock:
            self._lines.pop(placement, None)


def printable(text: str) -> str:
    """Every character outside printable ASCII (0x20 to 0x7E) written as `?`."""
    return "".join(c if " " <= c <= "~" else "?" for c in text)


# The scrub (security review A1838, note nte-46y7xkgz9njk): the hub's guard knows only the
# hub's own credential format, so the runner replaces other secrets itself. Each pattern
# starts at a word boundary of its own (`tsk-…` is no `sk-` key); a match becomes `<secret>`
# and the line is kept (the lead's ruling).
_LEFT = r"(?<![A-Za-z0-9_-])"
_TAIL = r"[A-Za-z0-9_.-]+"
_SECRET = re.compile(
    _LEFT
    + r"(?:"
    + r"gh[pousr]_" + _TAIL  # GitHub: personal, OAuth, user, server, refresh tokens
    + r"|github_pat_" + _TAIL  # GitHub: fine-grained personal tokens
    + r"|glpat-" + _TAIL  # GitLab personal tokens
    + r"|sk-" + _TAIL  # Anthropic (sk-ant-), OpenAI (sk-, sk-proj-), OpenRouter, Moonshot
    + r"|xai-" + _TAIL  # xAI (opencode with Grok)
    + r"|AIza" + _TAIL  # Google API keys (antigravity)
    + r"|ya29\." + _TAIL  # Google OAuth access tokens
    + r"|(?:AKIA|ASIA)[A-Z0-9]{16}[A-Za-z0-9]*"  # AWS access key ids
    + r"|xox[abprs]-[A-Za-z0-9-]+"  # Slack tokens
    + r")"
)  # fmt: skip
# `Authorization: <scheme> <value>` or `authorization=<value>`: the value, with its scheme.
_AUTHORIZATION = re.compile(
    r"(?i)(?<![A-Za-z0-9_-])(authorization\s*[:=]\s*)(?:[a-z][a-z0-9-]*\s+)?[^\s,;\"'<>]+"
)
_BEARER = re.compile(r"(?i)(?<![A-Za-z0-9_-])(bearer\s+)[A-Za-z0-9._~+/=-]+")
# A path that holds a user's name: under /home/<user>, /Users/<user>, C:\Users\<user> or
# C:/Users/<user>, or /root. The whole path becomes `<path>`, the only form a path may take in
# a log line (§15.7); the path is the run of characters between these stops.
_PATH_TOKEN = re.compile(r"[^\s\"'`<>|=,;()\[\]{}]+")
_USER_DIR = re.compile(r"[\\/](?:home|[Uu]sers)[\\/][^\\/]|[\\/]root(?![A-Za-z0-9_-])")


def _path(found: re.Match[str]) -> str:
    return "<path>" if _USER_DIR.search(found.group(0)) else found.group(0)


def scrub(line: str) -> str:
    """`line` with forge tokens, provider keys, authorization values and paths holding a
    user's name replaced by `<secret>` and `<path>`."""
    line = _SECRET.sub("<secret>", line)
    line = _AUTHORIZATION.sub(r"\1<secret>", line)
    line = _BEARER.sub(r"\1<secret>", line)
    return _PATH_TOKEN.sub(_path, line)


def log_entries(
    placement: str, entries: Iterable[tuple[float, str]], offset: float = 0.0
) -> list[dict[str, str]]:
    """`finding.log` (§15.7) from the runner's notes, oldest first: only lines that start with
    this placement's id; a line in the hub's credential format dropped (`sign.
    contains_credential`, the check the hub client runs on every body); the rest written as
    printable ASCII, scrubbed, cut at 1021 bytes plus `...`; then the oldest left out until at
    most 200 lines of at most 24 KiB remain. `at` is the line's time plus `offset`, in the
    wire form."""
    prefix = f"{placement}: "
    kept: list[dict[str, str]] = []
    for at, line in entries:
        if not isinstance(line, str) or not line.startswith(prefix):
            continue
        if sign.contains_credential(line):
            continue
        text = scrub(printable(line[:SCRUB_INPUT_MAX]))
        if sign.contains_credential(text):
            continue
        if len(text) > LOG_LINE_BYTES:
            text = text[:CUT_AT] + "..."
        if text:
            kept.append({"at": stamp(at + offset), "line": text})
    total = sum(len(entry["line"]) for entry in kept)
    first = 0
    while len(kept) - first > LOG_LINES_MAX or total > LOG_TOTAL_BYTES:
        total -= len(kept[first]["line"])
        first += 1
    return kept[first:]
