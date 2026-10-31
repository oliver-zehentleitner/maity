"""`maity jourfixe`, `answer`, `answers`, `withdraw`, and the jour fixe lines in `resume` and
`wait` (docs/api.md §13, §20)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import fakehub
import pytest
from test_onboarding import packet

from maity import cli, onboarding

BASE = "/api/v1/projects/oliver/maity/jour-fixe"
ROUND = f"{BASE}/rounds/jfx-0013"
ME = "agt-b"  # the member the `joined` fixture is


def _round(status: str = "answering", **fields: Any) -> dict[str, Any]:
    return {
        "id": "jfx-0013",
        "status": status,
        "scheduled_for": "2026-10-31T09:00:00Z",
        "answers_close_at": "2026-10-31T11:00:01Z",
        "steps": [],
        "invited": [{"member_id": ME, "kind": "agent", "instance": "wqe2"}],
        "participants": [{"member_id": ME, "kind": "agent", "handle": "agent-b"}],
        **fields,
    }


REPORTED = {
    "id": "jfx-0012",
    "status": "reported",
    "reported_at": "2026-10-29T15:02:00Z",
    "report": {
        "summary": "Reviews took too long.",
        "proposals": [{"id": "r1", "title": "Two reviewers per PR", "triage": "to_owner",
                       "request_id": "req-0091", "task_id": None}],  # fmt: skip
    },
}


def _overview(fake: fakehub.FakeHub, current: dict[str, Any] | None, **more: Any) -> None:
    body = {"policy": {}, "moderators": ["agt-a", "agt-c"], "next_at": "2026-11-05T09:00:00Z",
            "current_round": current, "last_round": REPORTED, **more}  # fmt: skip
    fake.routes[("GET", BASE)] = lambda seen: (200, body)


def _mine(fake: fakehub.FakeHub, items: list[dict[str, Any]]) -> None:
    fake.routes[("GET", f"{ROUND}/answers")] = lambda seen: (200, {"items": items})


def _posted(fake: fakehub.FakeHub) -> list[Any]:
    return [r.json() for r in fake.signed() if r.method == "POST" and r.path == f"{ROUND}/answers"]


# --- maity jourfixe ------------------------------------------------------------------------------


def test_the_overview_shows_slot_order_round_part_and_report(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    _overview(fake, _round())
    _mine(fake, [])
    assert cli.main(["jourfixe"]) == cli.EXIT_OK
    out = capsys.readouterr().out
    assert "Next jour fixe: 2026-11-05T09:00:00Z\n" in out
    assert "Moderator order: agt-a, agt-c\n" in out
    assert "Current round jfx-0013: answering, answers close at 2026-10-31T11:00:01Z\n" in out
    assert "  you were invited, not answered (`maity jourfixe answer`, or not at all)\n" in out
    assert "Last report: jfx-0012, 2026-10-29T15:02:00Z\n  > Reviews took too long.\n" in out
    assert "  - Two reviewers per PR [to_owner] -> req-0091\n" in out


@pytest.mark.parametrize(
    ("current", "mine", "part"),
    [
        (_round(), [{"id": None, "anonymous": True}], "you were invited, answered anonymously"),
        (_round(invited=[]), [], "you were not invited (not present when it opened)"),
        (
            _round("exchange", steps=[{"n": 2, "kind": "response", "closed_at": None,
                                       "eligible": [ME]}]),  # fmt: skip
            [],
            "you were invited, eligible in step 2",
        ),
    ],
)
def test_the_callers_part(
    current: dict[str, Any],
    mine: list[dict[str, Any]],
    part: str,
    joined: Path,
    fake: fakehub.FakeHub,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _overview(fake, current)
    _mine(fake, mine)
    assert cli.main(["jourfixe"]) == cli.EXIT_OK
    assert f"  {part}\n" in capsys.readouterr().out


def test_no_round_and_no_slot(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    _overview(fake, None, next_at=None, moderators=[], last_round=None)
    assert cli.main(["jourfixe"]) == cli.EXIT_OK
    out = capsys.readouterr().out
    assert out == "Next jour fixe: none scheduled\nModerator order: nobody\nNo round open\n"


def test_all_lists_every_page(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    pages = {
        "": {"items": [_round()], "next_cursor": "c2"},
        "c2": {"items": [REPORTED], "next_cursor": None},
    }

    def page(seen: fakehub.Seen) -> tuple[int, Any]:
        cursor = dict(p.split("=", 1) for p in seen.query.split("&") if p).get("cursor", "")
        return 200, pages[cursor]

    fake.routes[("GET", f"{BASE}/rounds")] = page
    assert cli.main(["jourfixe", "--all"]) == cli.EXIT_OK
    out = capsys.readouterr().out.splitlines()
    assert out[0].startswith("jfx-0013 2026-10-31T09:00:00Z: answering")
    assert out[1] == "jfx-0012 ?: reported"


# --- maity jourfixe answer -----------------------------------------------------------------------


def test_a_named_answer_is_posted_and_its_id_printed(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    _overview(fake, _round())
    fake.routes[("POST", f"{ROUND}/answers")] = lambda seen: (
        201,
        {"round_id": "jfx-0013", "anonymous": False, "id": "ans-7"},
    )
    argv = ["jourfixe", "answer", "--went-well", "fast reviews", "--would-help", "fewer pings"]
    assert cli.main(argv) == cli.EXIT_OK
    assert _posted(fake) == [
        {"went_well": "fast reviews", "would_help": "fewer pings", "anonymous": False}
    ]
    out, err = capsys.readouterr()
    assert out == "answered ans-7\n" and "anonymity" not in err


def test_an_anonymous_answer_prints_the_limits_first(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    _overview(fake, _round())
    fake.routes[("POST", f"{ROUND}/answers")] = lambda seen: (
        201,
        {"round_id": "jfx-0013", "anonymous": True},
    )
    assert cli.main(["jourfixe", "answer", "--went-badly", "x", "--anonymous"]) == cli.EXIT_OK
    out, err = capsys.readouterr()
    assert out == "answered\n"
    assert "It does not cover:" in err and "small rounds" in err
    assert _posted(fake) == [{"went_badly": "x", "anonymous": True}]


def test_the_answer_from_a_json_file(
    joined: Path, fake: fakehub.FakeHub, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _overview(fake, _round())
    fake.routes[("POST", f"{ROUND}/answers")] = lambda seen: (201, {"anonymous": False, "id": "a"})
    path = tmp_path / "answer.json"
    path.write_text(json.dumps({"went_well": "a\n\nb", "went_badly": None}))
    assert cli.main(["jourfixe", "answer", "--file", str(path)]) == cli.EXIT_OK
    assert _posted(fake) == [{"went_well": "a\n\nb", "anonymous": False}]


@pytest.mark.parametrize(
    ("current", "said"),
    [
        (None, "no jour fixe round is open for answers; nothing sent"),
        (_round("exchange"), "no jour fixe round is open for answers; nothing sent"),
        (_round(participants=[]), "you are not a participant of jfx-0013; nothing sent"),
    ],
)
def test_without_a_round_to_answer_it_exits_2_and_sends_nothing(
    current: dict[str, Any] | None,
    said: str,
    joined: Path,
    fake: fakehub.FakeHub,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _overview(fake, current)
    assert cli.main(["jourfixe", "answer", "--went-well", "x"]) == cli.EXIT_USAGE
    assert said in capsys.readouterr().err
    assert _posted(fake) == []


@pytest.mark.parametrize(
    "argv",
    [
        ["jourfixe", "answer"],  # nothing to say
        ["jourfixe", "answer", "--went-well", "  "],
        ["jourfixe", "answer", "--went-well", "x", "--file", "-"],  # both
    ],
)
def test_an_empty_or_doubled_answer_is_a_usage_error_before_any_call(
    argv: list[str], joined: Path, fake: fakehub.FakeHub
) -> None:
    assert cli.main(argv) == cli.EXIT_USAGE
    assert not fake.signed()


def test_a_file_with_other_keys_is_refused(
    joined: Path, fake: fakehub.FakeHub, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "answer.json"
    path.write_text(json.dumps({"went_well": "x", "author": "me"}))
    assert cli.main(["jourfixe", "answer", "--file", str(path)]) == cli.EXIT_USAGE
    assert "went_well, went_badly, would_help" in capsys.readouterr().err


def test_a_second_answer_says_so(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    _overview(fake, _round())
    fake.routes[("POST", f"{ROUND}/answers")] = lambda seen: (
        409,
        {"error": {"code": "jour_fixe_answered", "message": "answered"}},
    )
    assert cli.main(["jourfixe", "answer", "--went-well", "x"]) == cli.EXIT_ERROR
    assert "you have answered jfx-0013 already" in capsys.readouterr().err


# --- maity jourfixe answers / withdraw -----------------------------------------------------------


def test_answers_of_the_current_round_named_and_anonymous(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    _overview(fake, _round())
    _mine(fake, [
        {"id": "ans-1", "anonymous": False, "author": "agt-c", "withdrawn": False,
         "went_well": "pairing\nworked", "went_badly": None, "would_help": None},
        {"id": "ans-2", "anonymous": True, "went_well": None, "went_badly": "CI",
         "would_help": "faster runners"},
    ])  # fmt: skip
    assert cli.main(["jourfixe", "answers"]) == cli.EXIT_OK
    out = capsys.readouterr().out
    assert "ans-1, agt-c:\n  Went well:\n    > pairing\n    > worked\n" in out
    assert (
        "ans-2, anonymous:\n  Went badly:\n    > CI\n  Would help:\n    > faster runners\n" in out
    )


def test_answers_mine_asks_for_the_own_answer(joined: Path, fake: fakehub.FakeHub) -> None:
    _mine(fake, [])
    assert cli.main(["jourfixe", "answers", "jfx-0013", "--mine"]) == cli.EXIT_OK
    reads = [r for r in fake.signed() if r.path == f"{ROUND}/answers"]
    assert [r.query for r in reads] == ["mine=true"]
    assert not any(r.path == BASE for r in fake.signed())  # the round was named


def test_withdrawing_an_anonymous_answer_says_the_moderator_may_have_read_it(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    _overview(fake, _round())
    _mine(fake, [{"id": None, "anonymous": True}])
    fake.routes[("DELETE", f"{ROUND}/answers/mine")] = lambda seen: (
        200,
        {"round_id": "jfx-0013", "withdrawn": True},
    )
    assert cli.main(["jourfixe", "withdraw"]) == cli.EXIT_OK
    assert capsys.readouterr().out == "withdrawn; the moderator may already have read it\n"


# --- resume and wait -----------------------------------------------------------------------------

OPENED = {
    "seq": 40, "kind": "jour_fixe_opened", "actor": None, "subject": {"id": "jfx-0013"},
    "audience": ["instance:agt-b#wqe2"],
    "payload": {"round_id": "jfx-0013", "moderator": "agt-a",
                "questions": "1. What went well?\n2. What went badly?",
                "answers_close_at": "2026-10-31T11:00:01Z"},
}  # fmt: skip


@pytest.mark.parametrize(
    ("kind", "payload", "expected"),
    [
        ("jour_fixe_answers_closed", {"answers_received": 3, "statement_due_at": "T1"},
         "answers closed, 3 received; you moderate: read them with `maity jourfixe answers "
         "jfx-0013`, the statement is due by T1 (`maity jourfixe statement jfx-0013 --file …`)"),
        ("jour_fixe_step_opened", {"step": 2, "kind": "response", "closes_at": "T2",
                                   "topics": ["t1", "t2"]},
         "step 2 (response) is open for you until T2, topics t1, t2: `maity jourfixe post "
         'jfx-0013 --step 2 --topic <topic> "…"`'),
        ("jour_fixe_exchange_closed", {"report_due_at": "T3"},
         "the exchange closed; you moderate: the report is due by T3 "
         "(`maity jourfixe report jfx-0013 --file …`)"),
    ],
)  # fmt: skip
def test_each_waking_event_says_what_it_asks(
    kind: str, payload: dict[str, Any], expected: str
) -> None:
    event = {"kind": kind, "payload": {"round_id": "jfx-0013", **payload}}
    assert onboarding.jour_fixe_lines(event) == [f"jour fixe jfx-0013: {expected}"]


def test_other_events_get_no_jour_fixe_line() -> None:
    assert onboarding.jour_fixe_lines({"kind": "jour_fixe_reported", "payload": {}}) == []
    assert onboarding.jour_fixe_lines({"kind": "task_updated"}) == []


def test_resume_shows_the_opening_with_its_questions_quoted() -> None:
    base = packet(events={"items": [OPENED], "cursor": 40})
    text = onboarding.render({**base, "me": {**base["me"], "instance": "wqe2"}})
    assert (
        "  #40 jour_fixe_opened by the hub on jfx-0013\n"
        "  jour fixe jfx-0013 is open: answer by 2026-10-31T11:00:01Z with `maity jourfixe "
        "answer`, or not at all; the answer goes to the moderator only\n"
        "  > 1. What went well?\n  > 2. What went badly?\n"
    ) in text


def test_wait_prints_the_opening_on_stderr(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    fake.events = [OPENED]
    assert cli.main(["wait", "--timeout", "5"]) == cli.EXIT_OK
    out, err = capsys.readouterr()
    assert json.loads(out)[0]["kind"] == "jour_fixe_opened"
    assert "maity: jour fixe jfx-0013 is open: answer by 2026-10-31T11:00:01Z" in err
    assert "maity: > 1. What went well?" in err
