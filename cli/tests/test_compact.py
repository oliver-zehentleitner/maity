"""The compact `join`/`resume` text and `maity resume --full` (docs/api.md §13)."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from typing import Any

import fakehub
import pytest
from test_onboarding import packet

from maity import cli, onboarding, state

RESUME = "/api/v1/me/resume"
KINDS = ("task_updated", "probe_observed", "ticker", "member_updated", "task_created")
LOREM = "The lease is renewed by every checkpoint; a stale one goes back to the board.\n"


def _message(seq: int, to_me: bool, lines: int = 3) -> dict[str, Any]:
    return {
        "seq": seq,
        "kind": "message",
        "actor": {"member_id": "agt-a"},
        "payload": {"type": "notice", "to": "agt-b" if to_me else "all", "body": LOREM * lines},
        "audience": ["member:agt-b"] if to_me else ["member:agt-a", "member:agt-c"],
    }


def _answered(n: int) -> dict[str, Any]:
    return {
        "id": f"req-{n:04d}",
        "class": "decision",
        "title": f"Which store for card {n}?",
        "replies": [{"id": "r1", "label": "SQLite"}],
        "answer": {"by": "hum-1", "reply_id": "r1", "text": LOREM * 4},
    }


def realistic() -> dict[str, Any]:
    """A rejoin after weeks: hundreds of events, many answers, the rules in full."""
    events: list[dict[str, Any]] = []
    for seq in range(1000, 1300):
        if seq % 8 == 0:
            events.append(_message(seq, to_me=seq % 16 == 0, lines=6))
        else:
            kind = KINDS[seq % len(KINDS)]
            events.append({
                "seq": seq, "kind": kind, "actor": {"member_id": "agt-a"},
                "subject": {"id": f"tsk-{seq}"},
                "audience": ["member:agt-b"] if seq % 7 == 0 else ["member:agt-a"],
            })  # fmt: skip
    peers = [
        {"member_id": f"agt-{c}", "handle": f"agent-{c}", "trust": "member", "role": "coder",
         "presence": "online"}
        for c in "acdefgh"
    ]  # fmt: skip
    return packet(
        rules={"version": 7, "markdown": "## Rules\n\n" + "- Work lands as a pull request.\n" * 40},
        claims=[{"id": "tsk-4", "status": "in_progress", "title": "Leases",
                 "checkpoint": {"next_step": "the endpoint"}}],  # fmt: skip
        requests={
            "answered_since_cursor": [_answered(n) for n in range(30)],
            "mine_open": [],
            "to_answer": [],
        },
        events={"items": events, "cursor": 1299, "after": 999, "truncated": False},
        peers=peers,
    )


def test_the_default_text_of_a_realistic_rejoin_stays_under_8_kb(
    capsys: pytest.CaptureFixture[str],
) -> None:
    data = realistic()
    compact = onboarding.render(data, first=True).encode()
    full = onboarding.render(data, first=True, full=True).encode()
    with capsys.disabled():
        print(f"\ncompact join text: {len(compact)} bytes (full: {len(full)} bytes)")
    assert len(compact) < 8 * 1024
    assert len(full) > 4 * len(compact)  # the fixture is big enough to mean something


def test_only_the_last_events_for_me_are_shown_and_the_rest_counted() -> None:
    text = onboarding.render(realistic())
    events = text.split("Events since your last session:\n", 1)[1].split("\n\n", 1)[0]
    shown = [line for line in events.splitlines() if line.startswith("  #")]
    assert len(shown) == onboarding.COMPACT_EVENTS
    assert shown[-1].startswith("  #1296 ")  # the newest event for agt-b
    assert "#1001 " not in events  # not for agt-b
    not_shown = events.splitlines()[-1]
    assert not_shown.startswith("  Not shown: ")
    assert "earlier for you): maity resume --full" in not_shown
    assert "ticker" not in not_shown  # printed in the Ticker section, never counted twice


def test_an_instance_token_counts_as_for_me() -> None:
    event = {"seq": 5, "kind": "task_assigned", "subject": {"id": "tsk-9"},
             "audience": ["instance:agt-b#wqe2"]}  # fmt: skip
    base = packet(events={"items": [event], "cursor": 5})
    text = onboarding.render({**base, "me": {**base["me"], "instance": "wqe2"}})
    assert "  #5 task_assigned" in text
    assert "Not shown" not in text


def test_the_not_shown_line_names_five_kinds_by_count() -> None:
    items = [{"seq": n, "kind": f"kind{n % 7}", "audience": []} for n in range(70)]
    line = onboarding.render(packet(events={"items": items, "cursor": 70})).split("Not shown: ")
    assert line[1].startswith("70 events (10 kind0, 10 kind1, 10 kind2, 10 kind3, 10 kind4, …)")


def test_only_the_last_answers_are_shown() -> None:
    reqs = {"answered_since_cursor": [_answered(n) for n in range(30)]}
    text = onboarding.render(packet(requests=reqs))
    assert "req-0019" not in text and "req-0020" in text and "req-0029" in text
    assert "  … 20 earlier answers: maity resume --full" in text
    assert "req-0000" in onboarding.render(packet(requests=reqs), full=True)


def test_bodies_are_cut_shorter_in_the_compact_text() -> None:
    long = _message(9, to_me=True, lines=30)
    text = onboarding.render(packet(events={"items": [long], "cursor": 9}))
    kept = text.count("  > The lease")
    assert 0 < kept <= onboarding.COMPACT_LINES
    assert f"… (cut, {30 - kept} more lines: " in text
    full = onboarding.render(packet(events={"items": [long], "cursor": 9}), full=True)
    assert full.count("  > The lease") == 30


def test_a_long_summary_to_answer_is_cut_too() -> None:
    req = {"id": "req-1", "class": "decision", "title": "T", "summary": LOREM * 30}
    text = onboarding.render(packet(requests={"to_answer": [req]}))
    assert "more lines: maity resume --full)" in text


# --- the next step ---------------------------------------------------------------------------

WAIT_ON = (
    ", then start `maity wait` in the background and keep working from what it returns. "
    "Do not wait for your human in the terminal."
)


def _next(text: str) -> str:
    return text.rstrip().rsplit("\n\nNext: ", 1)[1].split("\n", 1)[0]


def test_after_a_join_without_work_the_agent_reports_to_its_lead() -> None:
    text = onboarding.render(packet(), first=True)
    assert _next(text) == 'Report to @agent-a with `maity say agent-a "…" --type notice`' + WAIT_ON


def test_without_a_lead_it_reports_to_its_human() -> None:
    base = packet()
    ms = {k: v for k, v in base["membership"].items() if k != "reports_to"}
    text = onboarding.render({**base, "membership": ms}, first=True)
    assert _next(text) == 'Report to your human with `maity say human "…"`' + WAIT_ON


def test_a_handover_is_read_first() -> None:
    handover = {"from": ["k7mq"], "items": [_message(3, to_me=True)], "after": 2}
    data = packet(claims=[{"id": "tsk-4", "status": "in_progress"}], handover=handover)
    expected = "Read what was handed over to you above, then continue tsk-4 from its checkpoint"
    assert _next(onboarding.render(data)) == expected + WAIT_ON


# --- maity resume --full -----------------------------------------------------------------------


def test_resume_stores_the_packet_privately_and_full_renders_it_without_the_hub(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    data = realistic()
    fake.routes[("POST", RESUME)] = lambda seen: (200, data)
    assert cli.main(["resume"]) == cli.EXIT_OK
    compact = capsys.readouterr().out
    stored = joined / cli.LAST_PACKET
    assert stat.S_IMODE(os.stat(stored).st_mode) == 0o600
    assert state.load_state(joined, name=cli.LAST_PACKET) == data

    calls = len(fake.seen)
    assert cli.main(["resume", "--full"]) == cli.EXIT_OK
    assert len(fake.seen) == calls  # no second session
    full = capsys.readouterr().out
    assert full == onboarding.render(data, full=True)
    assert len(full) > len(compact) and "Not shown" not in full

    assert cli.main(["resume", "--full", "--json"]) == cli.EXIT_OK
    assert json.loads(capsys.readouterr().out) == data


def test_full_without_a_stored_packet_resumes_and_prints_in_full(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    data = realistic()
    fake.routes[("POST", RESUME)] = lambda seen: (200, data)
    assert cli.main(["resume", "--full"]) == cli.EXIT_OK
    assert any(r.path == RESUME for r in fake.signed())
    assert "Not shown" not in capsys.readouterr().out
    assert (joined / cli.LAST_PACKET).is_file()


def test_join_prints_the_compact_text(
    clone: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    fake.routes[("POST", RESUME)] = lambda seen: (200, realistic())
    url = f"{fake.url}/j/{fakehub.TOKEN}"
    assert cli.main(["join", url, "--code", fakehub.CODE, "--no-pointer"]) == cli.EXIT_OK
    out = capsys.readouterr().out
    assert "Not shown: " in out and len(out.encode()) < 8 * 1024
