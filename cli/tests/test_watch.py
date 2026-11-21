"""The runner's watch, its pure parts (maity.runner.watch) and its settings (`[limits.watch]`):
docs/api.md §15.7 "A finding", §15.14 "The runner's watch"; card tsk-bzmd0avm4yhb."""

from __future__ import annotations

import subprocess
import tomllib
from pathlib import Path
from typing import Any

import pytest

from maity.runner import config, keeper, watch

MINIMAL = """\
[hub]
url = "https://hub.example"
state_dir = "/srv/state"

[limits]
projects = ["oliver/maity"]
repositories = ["github.com/oliver-zehentleitner/maity"]

[harness.stub]
"""

T0 = 1_800_000_000.0  # a hub time to count from
MIN = 60.0


def parse(extra: str = "") -> config.Config:
    return config.parse(tomllib.loads(MINIMAL + extra), Path("runner.toml"))


def problems(extra: str) -> list[str]:
    with pytest.raises(config.ConfigError) as info:
        parse(extra)
    return info.value.problems


# --- [limits.watch] --------------------------------------------------------------------------


def test_watch_settings_default_to_the_documented_values() -> None:
    found = parse().limits.watch
    assert found == config.Watch(15, 10, 1, 120)
    assert (
        found.not_listening_grace_minutes,
        found.join_within_minutes,
        found.auto_restarts,
        found.retry_window_minutes,
    ) == (15, 10, 1, 120)


def test_an_empty_watch_table_takes_the_defaults() -> None:
    assert parse("\n[limits.watch]\n").limits.watch == config.Watch()


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("not_listening_grace_minutes", 1),
        ("not_listening_grace_minutes", 1440),
        ("join_within_minutes", 1),
        ("join_within_minutes", 120),
        ("auto_restarts", 0),
        ("auto_restarts", 3),
        ("retry_window_minutes", 10),
        ("retry_window_minutes", 1440),
    ],
)
def test_watch_settings_take_their_range_edges(key: str, value: int) -> None:
    found = parse(f"\n[limits.watch]\n{key} = {value}\n").limits.watch
    assert getattr(found, key) == value


@pytest.mark.parametrize(
    ("key", "value", "reason"),
    [
        ("not_listening_grace_minutes", 0, "1 to 1440"),
        ("not_listening_grace_minutes", 1441, "1 to 1440"),
        ("join_within_minutes", 0, "1 to 120"),
        ("join_within_minutes", 121, "1 to 120"),
        ("auto_restarts", -1, "0 to 3"),
        ("auto_restarts", 4, "0 to 3"),
        ("retry_window_minutes", 9, "10 to 1440"),
        ("retry_window_minutes", 1441, "10 to 1440"),
    ],
)
def test_watch_settings_refuse_values_out_of_range(key: str, value: int, reason: str) -> None:
    assert problems(f"\n[limits.watch]\n{key} = {value}\n") == [f"limits.watch.{key}: {reason}"]


@pytest.mark.parametrize("value", ["true", "1.5", '"15"'])
def test_watch_settings_are_integers(value: str) -> None:
    assert problems(f"\n[limits.watch]\nauto_restarts = {value}\n") == [
        "limits.watch.auto_restarts: expected an integer"
    ]


def test_watch_settings_refuse_an_unknown_key() -> None:
    assert problems("\n[limits.watch]\ngrace_minutes = 5\n") == [
        "limits.watch.grace_minutes: unknown key"
    ]


# --- timestamps ------------------------------------------------------------------------------


def test_stamp_is_the_wire_form() -> None:
    assert watch.stamp(0) == "1970-01-01T00:00:00Z"
    assert watch.stamp(59.9) == "1970-01-01T00:00:59Z"
    assert watch.WIRE_TIMESTAMP.fullmatch(watch.stamp(T0))


@pytest.mark.parametrize(
    "value",
    [
        "2026-11-20T20:26:00+00:00",
        "2026-11-20T20:26:00.5Z",
        "2026-11-20 20:26:00Z",
        "2026-13-01T00:00:00Z",
        "1800000000",
        1800000000,
        None,
    ],
)
def test_parse_stamp_takes_the_wire_form_only(value: object) -> None:
    assert watch.parse_stamp(value) is None


def test_parse_stamp_round_trips() -> None:
    assert watch.parse_stamp(watch.stamp(T0)) == T0


def test_offset_from_server_time() -> None:
    assert watch.offset_from(watch.stamp(T0), T0 - 90) == 90
    assert watch.offset_from("soon", T0) is None


# --- session facts and triggers --------------------------------------------------------------


def session(**fields: object) -> dict[str, object]:
    base: dict[str, object] = {
        "started_at": None, "not_listening_since": None, "paused": False, "dormant": False,
    }  # fmt: skip
    return {"id": "plc-0003", "session": {**base, **fields}}


def test_session_facts_read_the_hubs_object() -> None:
    facts = watch.session_facts(session(started_at=watch.stamp(T0), paused=True))
    assert facts == watch.SessionFacts(T0, None, True, False)
    assert facts is not None and facts.resting


def test_session_null_or_absent_or_malformed_gives_no_facts() -> None:
    assert watch.session_facts({"session": None}) is None
    assert watch.session_facts({}) is None
    assert watch.session_facts(session(paused="no")) is None
    assert watch.session_facts(session(started_at="2026-11-20T20:26:00+00:00")) is None


def test_takes_finding_reads_the_keys_presence() -> None:
    assert watch.takes_finding({"session": None})
    assert not watch.takes_finding({})


def facts(
    started: float | None = None, quiet: float | None = None, paused: bool = False,
    dormant: bool = False,
) -> watch.SessionFacts:  # fmt: skip
    return watch.SessionFacts(started, quiet, paused, dormant)


def when(
    found: watch.SessionFacts | None, now: float, run: float | None = T0, interactive: bool = True
) -> str | None:
    return watch.trigger(
        found, interactive=interactive, run_started=run, hub_now=now, grace=15 * MIN,
        join_within=10 * MIN,
    )  # fmt: skip


def test_not_listening_past_the_grace() -> None:
    joined = facts(started=T0 + MIN, quiet=T0 + 20 * MIN)
    assert when(joined, T0 + 35 * MIN - 1) is None
    assert when(joined, T0 + 35 * MIN) == watch.NOT_LISTENING


def test_not_listening_counts_the_grace_from_this_runs_start() -> None:
    # The hub still reports the episode of the session before the restart.
    stale = facts(started=T0 + MIN, quiet=T0 - 60 * MIN)
    assert when(stale, T0 + 15 * MIN - 1) is None
    assert when(stale, T0 + 15 * MIN) == watch.NOT_LISTENING


def test_not_listening_on_an_adopted_session_counts_from_the_episode() -> None:
    assert when(facts(started=T0 - 99 * MIN, quiet=T0), T0 + 15 * MIN, run=None) == (
        watch.NOT_LISTENING
    )


def test_supervised_sessions_are_never_not_listening() -> None:
    joined = facts(started=T0 + MIN, quiet=T0 + MIN)
    assert when(joined, T0 + 99 * MIN, interactive=False) is None


def test_never_joined_after_join_within() -> None:
    assert when(facts(), T0 + 10 * MIN - 1) is None
    assert when(facts(), T0 + 10 * MIN) == watch.NEVER_JOINED
    assert when(facts(started=T0 - MIN), T0 + 10 * MIN) == watch.NEVER_JOINED  # an earlier one
    assert when(facts(started=T0 + MIN), T0 + 99 * MIN) is None


def test_never_joined_needs_a_known_start() -> None:
    assert when(facts(), T0 + 99 * MIN, run=None) is None


def test_never_joined_goes_first_when_both_hold() -> None:
    assert when(facts(started=T0 - 99 * MIN, quiet=T0 - 99 * MIN), T0 + 99 * MIN) == (
        watch.NEVER_JOINED
    )


@pytest.mark.parametrize("rest", [{"paused": True}, {"dormant": True}])
def test_resting_agents_have_no_trigger(rest: dict[str, bool]) -> None:
    assert when(facts(quiet=T0, **rest), T0 + 99 * MIN) is None
    assert when(facts(**rest), T0 + 99 * MIN) is None


def test_a_foreign_placement_has_no_trigger() -> None:
    assert when(None, T0 + 99 * MIN) is None


def test_the_grace_counts_from_watched_since_and_never_joined_keeps_to_the_run() -> None:
    # Adopted after the runner's own restart at T0: its start unknown, quiet for an hour.
    adopted = facts(quiet=T0 - 60 * MIN)

    def at(now: float) -> str | None:
        return watch.trigger(
            adopted, interactive=True, run_started=None, hub_now=now, grace=15 * MIN,
            join_within=10 * MIN, watched_since=T0,
        )  # fmt: skip

    assert at(T0) is None
    assert at(T0 + 15 * MIN - 1) is None
    assert at(T0 + 15 * MIN) == watch.NOT_LISTENING
    # No session started at all, yet no never_joined: the run's start is unknown.
    assert at(T0 + 99 * MIN) == watch.NOT_LISTENING
    assert watch.trigger(
        facts(), interactive=False, run_started=None, hub_now=T0 + 99 * MIN, grace=15 * MIN,
        join_within=10 * MIN, watched_since=T0,
    ) is None  # fmt: skip


def test_a_session_started_in_the_runs_second_counts_as_joined() -> None:
    # The hub's times have whole seconds: a session at T0 joined a run started at T0 + 0.6.
    def joined(started: float) -> str | None:
        return watch.trigger(
            facts(started=started), interactive=False, run_started=T0 + 0.6,
            hub_now=T0 + 99 * MIN, grace=15 * MIN, join_within=10 * MIN,
        )  # fmt: skip

    assert joined(T0) is None
    assert joined(T0 - 1) == watch.NEVER_JOINED


# --- the login probe (keeper.login_state, security review A1942) ----------------------------


class Probe:
    """A stand-in for AsUser.run: the probe's answer, or the exception it raises."""

    def __init__(
        self, code: int = 0, out: str = "", err: str = "", raises: Any = None,
        direct: bool = True,
    ) -> None:  # fmt: skip
        self.done = subprocess.CompletedProcess(["probe"], code, out, err)
        self.raises = raises
        self.direct = direct  # AsUser.direct: the runner's own user here
        self.env: Any = "not run"

    def run(
        self, argv: list[str], env: Any = None, **kwargs: Any
    ) -> subprocess.CompletedProcess[str]:
        self.env = env
        if self.raises is not None:
            raise self.raises
        return self.done


def login(harness: str, probe: Probe, binary: str | None = "/bin/tool") -> str:
    return keeper.login_state(harness, binary, probe)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("harness", "probe", "answer"),
    [
        ("claude-code", Probe(0), "ok"),
        ("claude-code", Probe(1), "needed"),  # its documented "not logged in"
        ("claude-code", Probe(2), "unknown"),
        ("claude-code", Probe(127), "unknown"),
        ("claude-code", Probe(126), "unknown"),
        ("claude-code", Probe(255), "unknown"),  # ssh could not reach the host
        ("claude-code", Probe(-9), "unknown"),  # killed by a signal
        ("codex", Probe(255, err="Not logged in\n"), "unknown"),
        ("codex", Probe(-9), "unknown"),
        ("claude-code", Probe(raises=subprocess.TimeoutExpired("claude", 30)), "unknown"),
        ("claude-code", Probe(raises=OSError("no such binary")), "unknown"),
        ("codex", Probe(0, out="Logged in using ChatGPT\n"), "ok"),
        ("codex", Probe(1, err="Not logged in\n"), "needed"),  # its documented answer
        ("codex", Probe(1, err="Error checking login status: disk full\n"), "unknown"),
        ("codex", Probe(1), "unknown"),
        ("codex", Probe(2, err="Not logged in\n"), "unknown"),
        ("codex", Probe(raises=subprocess.TimeoutExpired("codex", 30)), "unknown"),
        ("opencode", Probe(1), "unknown"),  # no probe
        ("antigravity", Probe(1), "unknown"),
    ],
)
def test_only_the_documented_answer_is_a_needed_login(
    harness: str, probe: Probe, answer: str
) -> None:
    assert login(harness, probe) == answer


def test_no_binary_is_an_unknown_login() -> None:
    assert login("claude-code", Probe(1), binary=None) == "unknown"


def test_the_probe_runs_with_the_agents_path_through_sudo_or_ssh() -> None:
    path = "/usr/local/bin:/usr/bin:/bin"
    remote = Probe(0, direct=False)
    found = keeper.login_state("claude-code", "/bin/c", remote, path)  # type: ignore[arg-type]
    assert found == "ok" and remote.env == {"PATH": path}
    here = Probe(0)
    found = keeper.login_state("claude-code", "/bin/c", here, path)  # type: ignore[arg-type]
    assert found == "ok" and here.env is None  # the runner's own environment, as before


# --- signals and the diagnosis ---------------------------------------------------------------


def sig(**fields: object) -> dict[str, object]:
    base: dict[str, object] = {
        "process": "alive", "exit_code": None, "below": "idle", "pane_match": [],
        "login": "ok", "pickup_code": None,
    }  # fmt: skip
    return watch.signals(**{**base, **fields})  # type: ignore[arg-type]


def test_signals_carry_every_key() -> None:
    assert tuple(sig()) == (
        "process", "exit_code", "below", "pane_match", "login", "pickup_code",
    )  # fmt: skip


def test_signals_of_a_gone_process_have_nothing_below_and_an_alive_one_no_exit_code() -> None:
    assert sig(process="gone", exit_code=1, below="waiting")["below"] == "unknown"
    assert sig(process="gone", exit_code=1)["exit_code"] == 1
    assert sig(process="alive", exit_code=1)["exit_code"] is None


@pytest.mark.parametrize(
    "bad",
    [
        {"process": "dead"},
        {"below": "busy"},
        {"login": "expired"},
        {"exit_code": True},
        {"exit_code": 2**31},
        {"pane_match": ["usage_limit", "usage_limit"]},
        {"pane_match": ["screen_text"]},
        {"pickup_code": "Not A Code"},
        {"pickup_code": "forbidden\n"},
    ],
)
def test_signals_refuse_what_the_hub_refuses(bad: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        sig(**bad)


def cause(
    trigger: str, found: dict[str, object], limit: bool = False, quiet: float | None = 0.0
) -> str | None:
    return watch.diagnose(
        trigger, found, limit_exit=limit, quiet_for=quiet, tool_call_max=120 * MIN
    )


def test_login_goes_first() -> None:
    found = sig(login="needed", process="gone", exit_code=22)
    assert cause(watch.NOT_LISTENING, found, limit=True) == "login_invalid"


def test_usage_limit_before_an_exit() -> None:
    assert cause(watch.NEVER_JOINED, sig(process="gone", exit_code=22), limit=True) == (
        "usage_limit"
    )


def test_harness_exited() -> None:
    assert cause(watch.NOT_LISTENING, sig(process="gone", exit_code=1)) == "harness_exited"
    assert cause(watch.NEVER_JOINED, sig(process="gone", exit_code=0)) == "harness_exited"


def test_not_listening_by_what_runs_below() -> None:
    assert cause(watch.NOT_LISTENING, sig(below="waiting")) == "wait_deaf"
    assert cause(watch.NOT_LISTENING, sig(below="idle")) == "not_waiting"
    assert cause(watch.NOT_LISTENING, sig(below="unknown")) == "unknown"


def test_work_below_is_looked_at_again_until_tool_call_max() -> None:
    working = sig(below="working")
    assert cause(watch.NOT_LISTENING, working, quiet=120 * MIN - 1) is None
    assert cause(watch.NOT_LISTENING, working, quiet=120 * MIN) == "unknown"


def test_never_joined_whatever_runs_below() -> None:
    for below in ("waiting", "working", "idle", "unknown"):
        assert cause(watch.NEVER_JOINED, sig(below=below)) == "never_joined"


def test_a_pane_match_decides_nothing_alone() -> None:
    found = sig(below="idle", pane_match=["usage_limit", "login_prompt"])
    assert cause(watch.NOT_LISTENING, found) == "not_waiting"


def test_no_login_probe_lets_the_diagnosis_go_on() -> None:
    found = sig(login="unknown", below="waiting", pane_match=["login_prompt"])
    assert cause(watch.NOT_LISTENING, found) == "wait_deaf"


# --- the finding -----------------------------------------------------------------------------


def test_finding_has_the_contracts_shape() -> None:
    built = watch.finding("wait_deaf", T0, sig(below="waiting"))
    assert set(built) == {"cause", "seen_at", "signals"}
    assert built["seen_at"] == watch.stamp(T0)
    assert built["signals"]["below"] == "waiting"


def test_finding_carries_its_log_when_there_is_one() -> None:
    log = [{"at": watch.stamp(T0), "line": "plc-0003: started"}]
    assert watch.finding("unknown", T0, sig(), log)["log"] == log


def test_finding_refuses_an_unknown_cause() -> None:
    with pytest.raises(ValueError):
        watch.finding("tired", T0, sig())


def test_the_lists_are_the_hubs() -> None:
    assert watch.CAUSES == (
        "harness_exited", "not_waiting", "wait_deaf", "never_joined", "usage_limit",
        "login_invalid", "pickup_refused", "unknown",
    )  # fmt: skip
    assert watch.PANE_CODES == ("usage_limit", "login_prompt")
    restarting = {"harness_exited", "wait_deaf", "never_joined", "unknown"}
    assert set(watch.RESTART_CAUSES) == restarting


# --- the pane's signatures -------------------------------------------------------------------


def test_no_signature_is_verified_yet() -> None:
    assert watch.PANE_SIGNATURES == ()
    assert watch.pane_texts("claude-code", "2.1.300") == ()
    assert watch.pane_match("claude-code", "2.1.300", {"anything"}) == []


def test_a_signature_matches_only_its_harness_and_versions() -> None:
    known = (
        watch.PaneSignature("codex", ("0.169.0",), "login_prompt", "Sign in"),
        watch.PaneSignature("codex", ("0.169.0",), "usage_limit", "limit reached"),
    )
    assert watch.pane_texts("codex", "0.169.0", known) == ("Sign in", "limit reached")
    shown = {"limit reached", "Sign in"}
    assert watch.pane_match("codex", "0.169.0", shown, known) == ["usage_limit", "login_prompt"]
    assert watch.pane_match("codex", "0.170.0", shown, known) == []
    assert watch.pane_match("codex", None, shown, known) == []
    assert watch.pane_match("claude-code", "0.169.0", shown, known) == []
    assert watch.pane_match("codex", "0.169.0", None, known) == []


# --- the cap ---------------------------------------------------------------------------------


def test_the_cap_allows_auto_restarts_within_the_window() -> None:
    window = 120 * MIN
    assert watch.may_restart([], T0, window, 1) == (True, [])
    assert watch.may_restart([T0 - MIN], T0, window, 1) == (False, [T0 - MIN])
    assert watch.may_restart([T0 - window], T0, window, 1) == (True, [])
    assert watch.may_restart([T0 - MIN], T0, window, 2) == (True, [T0 - MIN])
    assert watch.may_restart([], T0, window, 0) == (False, [])


def test_hung_report() -> None:
    exited = watch.hung_report(watch.NOT_LISTENING, held=False)
    assert exited == ("exited", "hung", "not_listening")
    held = watch.hung_report(watch.NEVER_JOINED, held=True)
    assert held == ("failed", "hung", "never_joined")


# --- the notes -------------------------------------------------------------------------------


def test_notes_keep_each_placements_lines_with_its_id() -> None:
    notes = watch.Notes()
    assert notes.add("plc-0003", T0, "started claude-code") == "plc-0003: started claude-code"
    notes.add("plc-0004", T0, "started codex")
    assert notes.entries("plc-0003") == [(T0, "plc-0003: started claude-code")]
    notes.forget("plc-0003")
    assert notes.entries("plc-0003") == []
    assert len(notes.entries("plc-0004")) == 1


def test_notes_keep_the_newest_lines() -> None:
    notes = watch.Notes()
    for n in range(watch.LOG_LINES_MAX + 5):
        notes.add("plc-0003", T0 + n, f"line {n}")
    kept = notes.entries("plc-0003")
    assert len(kept) == watch.LOG_LINES_MAX
    assert kept[0][1] == "plc-0003: line 5"


# --- the scrub -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "secret",
    [
        "ghp_abcDEF0123456789abcdef0123456789abcd",
        "gho_abcDEF0123456789",
        "ghu_abcDEF0123456789",
        "ghs_abcDEF0123456789",
        "ghr_abcDEF0123456789",
        "github_pat_11ABCDEFG0_abcdefghijklmnopqrstuvwxyz",
        "glpat-abcDEF0123456789xyz",
        "sk-ant-api03-abcDEF_0123456789-xyz",
        "sk-proj-abcDEF0123456789",
        "sk-abcDEF0123456789",
        "xai-abcDEF0123456789",
        "AIzaSyA1234567890abcdefghijklmnopqrstu",
        "ya29.a0AfH6SMBabcdef",
        "AKIAIOSFODNN7EXAMPLE",
        "ASIAIOSFODNN7EXAMPLE",
        "xoxa-123-456-abc",
        "xoxb-123456789012-abcDEF",
        "xoxp-1-2-3-abc",
        "xoxr-abc",
        "xoxs-abc-def",
        "sk_live_51HabcdefGHIJKLMNOP",
        "sk_test_abcdefghijklmnop12",
        "rk_live_abcdefghijklmnop12",
        "rk_test_abcdefghijklmnop12",
        "hf_abcdefghijklmnopqrstuvwxyz12",
        "npm_abcdefghijklmnopqrstuvwxyz1234",
    ],
)
def test_scrub_replaces_each_kind_of_secret(secret: str) -> None:
    assert watch.scrub(f"plc-0003: token {secret} seen") == "plc-0003: token <secret> seen"
    assert watch.scrub(f"plc-0003: key={secret}") == "plc-0003: key=<secret>"


@pytest.mark.parametrize(
    ("line", "scrubbed"),
    [
        ("plc-0003: clone https://bob:hunter2@github.com/o/r failed",
         "plc-0003: clone https://<secret>@github.com/o/r failed"),
        ("plc-0003: clone https://x-access-token:ghs_abc@github.com/o/r",
         "plc-0003: clone https://<secret>@github.com/o/r"),
        ("plc-0003: push to https://abc123token@gitlab.example/o/r",
         "plc-0003: push to https://<secret>@gitlab.example/o/r"),
        ("plc-0003: ssh://git@github.com:22/o/r", "plc-0003: ssh://<secret>@github.com:22/o/r"),
    ],
)  # fmt: skip
def test_scrub_replaces_a_urls_userinfo_and_keeps_scheme_and_host(line: str, scrubbed: str) -> None:
    assert watch.scrub(line) == scrubbed


@pytest.mark.parametrize(
    "line",
    [
        "plc-0003: tsk_live_abcdefghijklmnopqrstuv",
        "plc-0003: ask_live_abcdefghijklmnopqrstuv",
        "plc-0003: hf_hub_download and npm_install_x",
        "plc-0003: my_npm_abcdefghijklmnopqrstuvwxyz",
        "plc-0003: sk_live_short",
        "plc-0003: https://hub.example/x and mail me@example.org",
    ],
)
def test_scrub_leaves_underscore_names_and_plain_urls_alone(line: str) -> None:
    assert watch.scrub(line) == line


def test_scrub_replaces_an_authorization_value() -> None:
    assert watch.scrub("plc-0003: Authorization: Bearer abc.DEF-123") == (
        "plc-0003: Authorization: <secret>"
    )
    plain = watch.scrub("plc-0003: authorization=token abc123")
    assert plain == "plc-0003: authorization=<secret>"
    assert watch.scrub("plc-0003: AUTHORIZATION: abc123, next") == (
        "plc-0003: AUTHORIZATION: <secret>, next"
    )


@pytest.mark.parametrize(
    ("line", "scrubbed"),
    [
        ("plc-0003: authorization='abc123'", "plc-0003: authorization='<secret>'"),
        ('plc-0003: {"Authorization": "Bearer abc.DEF"}',
         'plc-0003: {"Authorization": "<secret>"}'),
        ("plc-0003: headers {'authorization': 'token abc'}",
         "plc-0003: headers {'authorization': '<secret>'}"),
    ],
)  # fmt: skip
def test_scrub_replaces_a_quoted_authorization_value(line: str, scrubbed: str) -> None:
    assert watch.scrub(line) == scrubbed


def test_scrub_replaces_a_bearer_token_anywhere() -> None:
    assert watch.scrub("plc-0003: sent Bearer abc.DEF/123+= then") == (
        "plc-0003: sent Bearer <secret> then"
    )
    assert watch.scrub("plc-0003: bearer xyz") == "plc-0003: bearer <secret>"


@pytest.mark.parametrize(
    ("line", "scrubbed"),
    [
        ("plc-0003: cwd /home/alice/repo done", "plc-0003: cwd <path> done"),
        ("plc-0003: cwd /Users/bob/repo done", "plc-0003: cwd <path> done"),
        ("plc-0003: cwd C:\\Users\\carol\\repo done", "plc-0003: cwd <path> done"),
        ("plc-0003: cwd C:/Users/dave/repo done", "plc-0003: cwd <path> done"),
        ("plc-0003: cwd c:\\users\\erin done", "plc-0003: cwd <path> done"),
        ("plc-0003: cwd C:\\USERS\\frank\\repo done", "plc-0003: cwd <path> done"),
        ("plc-0003: cwd c:/users/gina done", "plc-0003: cwd <path> done"),
        ("plc-0003: cwd /USERS/hal/repo done", "plc-0003: cwd <path> done"),
        ("plc-0003: cwd /root/.config done", "plc-0003: cwd <path> done"),
        ("plc-0003: cwd /root done", "plc-0003: cwd <path> done"),
        ("plc-0003: HOME=/home/alice", "plc-0003: HOME=<path>"),
        ("plc-0003: in '/home/alice/x'", "plc-0003: in '<path>'"),
        ("plc-0003: at /srv/data/home/alice/x", "plc-0003: at <path>"),
    ],
)
def test_scrub_replaces_paths_that_hold_a_user_name(line: str, scrubbed: str) -> None:
    assert watch.scrub(line) == scrubbed


@pytest.mark.parametrize(
    "line",
    [
        "plc-0003: card tsk-twmms66p1ww4 done",
        "plc-0003: task-abcdefgh",
        "plc-0003: risk-free",
        "plc-0003: running as root",
        "plc-0003: /rooted/x and /srv/state/x and /home/",
        "plc-0003: exited 1 (generation 4, restart 2)",
        "plc-0003: x_ghp_abcdef0123 and AKIA1234",
        "plc-0003: <path> and <secret> stay",
        "plc-0003: not listening since 20:09Z, a maity wait runs: restart, resuming",
    ],
)
def test_scrub_leaves_runner_text_alone(line: str) -> None:
    assert watch.scrub(line) == line


# --- finding.log -----------------------------------------------------------------------------


def entries(*lines: str, at: float = T0) -> list[tuple[float, str]]:
    return [(at + n, line) for n, line in enumerate(lines)]


def test_log_takes_only_this_placements_lines() -> None:
    got = watch.log_entries(
        "plc-1",
        entries("plc-1: started", "plc-10: started", "plc-2: started", "supervisor: x",
                "plc-1 without the colon", "plc-1: exited 1"),
    )  # fmt: skip
    assert [e["line"] for e in got] == ["plc-1: started", "plc-1: exited 1"]


def test_log_times_are_hub_time_in_the_wire_form() -> None:
    got = watch.log_entries("plc-1", [(T0, "plc-1: started")], offset=90)
    assert got == [{"at": watch.stamp(T0 + 90), "line": "plc-1: started"}]


def test_log_drops_a_line_in_the_hubs_credential_format() -> None:
    got = watch.log_entries("plc-1", entries("plc-1: mty1.cred0123.secretPART_x-y", "plc-1: kept"))
    assert [e["line"] for e in got] == ["plc-1: kept"]


def test_log_scrubs_each_line() -> None:
    got = watch.log_entries("plc-1", entries("plc-1: token ghp_abcdef012345 at /home/alice/x"))
    assert got[0]["line"] == "plc-1: token <secret> at <path>"


def test_log_writes_printable_ascii() -> None:
    got = watch.log_entries("plc-1", entries("plc-1: caf\u00e9\tok\n"))
    assert got[0]["line"] == "plc-1: caf??ok?"


def test_log_cuts_a_long_line() -> None:
    exact = "plc-1: " + "a" * (watch.LOG_LINE_BYTES - len("plc-1: "))
    longer = exact + "b"
    got = watch.log_entries("plc-1", entries(exact, longer))
    assert got[0]["line"] == exact
    assert len(got[1]["line"]) == watch.LOG_LINE_BYTES
    assert got[1]["line"] == longer[: watch.CUT_AT] + "..."


def test_log_scrubs_before_it_cuts() -> None:
    secret = "ghp_" + "x" * 40
    line = "plc-1: " + "a" * 1010 + " " + secret  # the secret straddles the cut
    got = watch.log_entries("plc-1", entries(line))
    assert "ghp_" not in got[0]["line"]
    assert got[0]["line"].endswith("...")


def test_log_scrubs_a_runaway_line() -> None:
    line = "plc-1: ghp_abcdef012345 " + "a" * 10_000
    got = watch.log_entries("plc-1", entries(line))
    assert got[0]["line"].startswith("plc-1: <secret> aaa")
    assert len(got[0]["line"]) == watch.LOG_LINE_BYTES


def test_log_keeps_the_newest_200_lines() -> None:
    lines = [f"plc-1: line {n}" for n in range(watch.LOG_LINES_MAX + 1)]
    got = watch.log_entries("plc-1", entries(*lines))
    assert len(got) == watch.LOG_LINES_MAX
    assert got[0]["line"] == "plc-1: line 1"
    assert got[-1]["line"] == f"plc-1: line {watch.LOG_LINES_MAX}"


def test_log_keeps_within_24_kib() -> None:
    line = "plc-1: " + "a" * (1000 - len("plc-1: "))  # 1000 bytes
    got = watch.log_entries("plc-1", entries(*[line] * 30))
    assert len(got) == 24  # 24 000 bytes; 25 would pass 24 576
    assert sum(len(e["line"]) for e in got) <= watch.LOG_TOTAL_BYTES
    assert got[-1]["at"] == watch.stamp(T0 + 29)  # the newest kept


def test_log_lines_meet_the_hubs_bounds() -> None:
    wide = "\u00fc" * 2000
    got = watch.log_entries("plc-1", entries(*[f"plc-1: {wide} {n}" for n in range(300)]))
    assert len(got) <= watch.LOG_LINES_MAX
    assert sum(len(e["line"]) for e in got) <= watch.LOG_TOTAL_BYTES
    for entry in got:
        assert 1 <= len(entry["line"].encode("ascii")) <= watch.LOG_LINE_BYTES
        assert watch.WIRE_TIMESTAMP.fullmatch(entry["at"])
