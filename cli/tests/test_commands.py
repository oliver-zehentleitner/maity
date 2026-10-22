"""The convenience commands: each one call, signed, with an idempotency key on writes."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import fakehub
import pytest
from conftest import git

from maity import cli, state

TASK = "/api/v1/projects/maity/tasks/tsk-0004"


def answer(fake: fakehub.FakeHub, method: str, path: str, payload: Any, status: int = 200) -> None:
    fake.routes[(method, path)] = lambda seen: (status, payload)


def last(fake: fakehub.FakeHub) -> fakehub.Seen:
    return fake.signed()[-1]


def release_card(card: str = "tsk-0010", status: str = "in_progress") -> dict[str, Any]:
    return {
        "id": card,
        "kind": "release",
        "status": status,
        "release": {
            "version": "0.1.0",
            "checklist": [
                {"id": "chk-1", "text": "CHANGELOG has a section", "done": True},
                {"id": "chk-2", "text": "live version equals the tag", "done": False},
            ],
            "readiness": {
                "ready": False,
                "blocking": [
                    {"reason": "pr_open", "pr": 3},
                    {"reason": "checklist_open", "item": "chk-2"},
                ],
            },
        },
    }


# --- claim and unclaim -----------------------------------------------------------------------


def test_claim_posts_once_with_an_idempotency_key(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    answer(fake, "POST", f"{TASK}/claim", {"id": "tsk-0004", "claim": {"lease_until": "T1"}})
    assert cli.main(["claim", "tsk-0004"]) == cli.EXIT_OK
    seen = last(fake)
    assert (seen.method, seen.path, seen.json()) == ("POST", f"{TASK}/claim", {})
    assert len(seen.headers["idempotency-key"]) >= 16
    assert capsys.readouterr().out == "claimed tsk-0004; lease until T1\n"


def test_claim_sends_the_reason(joined: Path, fake: fakehub.FakeHub) -> None:
    answer(fake, "POST", f"{TASK}/claim", {"id": "tsk-0004"})
    assert cli.main(["claim", "tsk-0004", "--reason", "fixes the release blocker"]) == 0
    assert last(fake).json() == {"reason": "fixes the release blocker"}


def test_claim_json_prints_the_card(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    card = {"id": "tsk-0004", "status": "in_progress", "claim": {"holder": "agt-b"}}
    answer(fake, "POST", f"{TASK}/claim", card)
    assert cli.main(["claim", "tsk-0004", "--json"]) == cli.EXIT_OK
    assert json.loads(capsys.readouterr().out) == card


def test_a_refused_claim_is_exit_1_with_the_hub_code(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    refusal = {"error": {"code": "already_claimed", "message": "held by agt-c", "details": {}}}
    answer(fake, "POST", f"{TASK}/claim", refusal, status=409)
    assert cli.main(["claim", "tsk-0004"]) == cli.EXIT_ERROR
    assert "already_claimed" in capsys.readouterr().err


def test_unclaim_calls_release_on_the_card(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    answer(fake, "POST", f"{TASK}/release", {"id": "tsk-0004", "status": "open", "claim": None})
    assert cli.main(["unclaim", "tsk-0004"]) == cli.EXIT_OK
    assert last(fake).path == f"{TASK}/release"
    assert "idempotency-key" in last(fake).headers
    assert capsys.readouterr().out == "gave tsk-0004 back; it is open again\n"


def test_card_ids_are_one_path_segment(joined: Path, fake: fakehub.FakeHub) -> None:
    cli.main(["claim", "../members/agt-a"])
    assert last(fake).path == "/api/v1/projects/maity/tasks/..%2Fmembers%2Fagt-a/claim"


# --- checkpoint ------------------------------------------------------------------------------


def test_checkpoint_takes_branch_and_head_from_git(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    answer(fake, "POST", f"{TASK}/checkpoint", {"id": "tsk-0004"})
    head = git(joined.parent.parent, "rev-parse", "HEAD")
    assert cli.main(["checkpoint", "tsk-0004", "-m", "table written", "--next", "endpoint"]) == 0
    assert last(fake).json() == {
        "last_step": "table written",
        "next_step": "endpoint",
        "head": head,
        "branch": "work",
    }
    assert capsys.readouterr().out == f"checkpoint on tsk-0004 at {head[:12]} on work\n"


def test_checkpoint_on_a_detached_head_sends_no_branch(joined: Path, fake: fakehub.FakeHub) -> None:
    work = joined.parent.parent
    git(work, "switch", "--quiet", "--detach")
    answer(fake, "POST", f"{TASK}/checkpoint", {"id": "tsk-0004"})
    assert cli.main(["checkpoint", "tsk-0004", "-m", "a", "--next", "b"]) == cli.EXIT_OK
    body = last(fake).json()
    assert "branch" not in body and body["head"] == git(work, "rev-parse", "HEAD")


def test_checkpoint_needs_both_steps() -> None:
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["checkpoint", "tsk-0004", "-m", "only the last"])


def test_an_empty_step_is_a_usage_error(joined: Path, fake: fakehub.FakeHub) -> None:
    assert cli.main(["checkpoint", "tsk-0004", "-m", " ", "--next", "b"]) == cli.EXIT_USAGE
    assert fake.signed() == []


# --- say -------------------------------------------------------------------------------------


def test_say_posts_a_typed_message(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    answer(fake, "POST", "/api/v1/projects/maity/events", {"seq": 4300, "kind": "message"})
    argv = ["say", "role:admin", "the exchange needs a lease", "--type", "blocker"]
    assert cli.main([*argv, "--task", "tsk-0004"]) == cli.EXIT_OK
    assert last(fake).json() == {
        "kind": "message",
        "type": "blocker",
        "to": "role:admin",
        "body": "the exchange needs a lease",
        "task_id": "tsk-0004",
    }
    assert capsys.readouterr().out == "sent blocker to role:admin (seq 4300)\n"


def test_say_to_members_needs_a_type(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["say", "agt-a", "hello"]) == cli.EXIT_USAGE
    assert "--type is required" in capsys.readouterr().err
    assert fake.signed() == []


def test_say_offers_no_chat_type() -> None:
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["say", "agt-a", "hi", "--type", "chat"])


def test_say_human_writes_into_the_own_conversation(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    path = "/api/v1/projects/maity/conversations/agt-b/messages"
    answer(fake, "POST", path, {"id": "evt-4237", "seq": 4237, "body": "done with the table"})
    assert cli.main(["say", "human", "done with the table"]) == cli.EXIT_OK
    assert (last(fake).path, last(fake).json()) == (path, {"body": "done with the table"})
    assert capsys.readouterr().out == "said to your human (seq 4237)\n"


def test_say_human_takes_no_type(joined: Path, fake: fakehub.FakeHub) -> None:
    assert cli.main(["say", "human", "hi", "--type", "notice"]) == cli.EXIT_USAGE
    assert fake.signed() == []


def test_say_human_needs_the_member_id(joined: Path, fake: fakehub.FakeHub) -> None:
    data = state.load_state(joined)
    del data["member_id"]
    state.save_state(joined, data)
    assert cli.main(["say", "human", "hi"]) == cli.EXIT_ERROR
    assert fake.signed() == []


def test_a_message_carrying_a_credential_is_refused_locally(
    joined: Path, fake: fakehub.FakeHub
) -> None:
    leaked = f"here it is: {fakehub.CREDENTIAL}"
    assert cli.main(["say", "all", leaked, "--type", "notice"]) == cli.EXIT_ERROR
    assert fake.signed() == []


# --- answer ----------------------------------------------------------------------------------


REQ = "/api/v1/projects/maity/requests/req-0012/answer"


@pytest.mark.parametrize(
    ("argv", "body"),
    [
        (["--reply", "o2"], {"reply_id": "o2"}),
        (["--text", "use the lease"], {"text": "use the lease"}),
        (["--reply", "o1", "--text", "with a pepper"], {"reply_id": "o1", "text": "with a pepper"}),
    ],
)
def test_answer_sends_reply_text_or_both(
    joined: Path, fake: fakehub.FakeHub, argv: list[str], body: dict[str, str]
) -> None:
    answer(fake, "POST", REQ, {"id": "req-0012", "status": "answered"})
    assert cli.main(["answer", "req-0012", *argv]) == cli.EXIT_OK
    assert last(fake).json() == body
    assert "idempotency-key" in last(fake).headers


def test_answer_needs_something_to_say(joined: Path, fake: fakehub.FakeHub) -> None:
    assert cli.main(["answer", "req-0012"]) == cli.EXIT_USAGE
    assert fake.signed() == []


def test_answer_prints_the_new_status(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    answer(fake, "POST", REQ, {"id": "req-0012", "status": "answered"})
    cli.main(["answer", "req-0012", "--reply", "o1"])
    assert capsys.readouterr().out == "answered req-0012; it is answered\n"


# --- release ---------------------------------------------------------------------------------


TASKS = "/api/v1/projects/maity/tasks"


def test_release_list_follows_the_pages(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    pages = {
        "": {"items": [release_card("tsk-0010")], "next_cursor": "p2"},
        "p2": {"items": [release_card("tsk-0003", "done")], "next_cursor": None},
    }

    def route(seen: fakehub.Seen) -> tuple[int, Any]:
        cursor = dict(p.split("=", 1) for p in seen.query.split("&")).get("cursor", "")
        return 200, pages[cursor]

    fake.routes[("GET", TASKS)] = route
    assert cli.main(["release", "list"]) == cli.EXIT_OK
    assert capsys.readouterr().out.splitlines() == [
        "tsk-0010  0.1.0  in_progress  ready: no",
        "tsk-0003  0.1.0  done  ready: no",
    ]
    first = fake.signed()[0].query
    assert "kind=release" in first and "status=all" in first


def test_release_show_picks_the_one_in_flight(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    items = [release_card("tsk-0003", "done"), release_card("tsk-0010")]
    answer(fake, "GET", TASKS, {"items": items, "next_cursor": None})
    assert cli.main(["release", "show"]) == cli.EXIT_OK
    assert capsys.readouterr().out.splitlines() == [
        "tsk-0010  0.1.0  in_progress  ready: no",
        "  blocking: pr_open pr=3",
        "  blocking: checklist_open item=chk-2",
        "  [x] chk-1  CHANGELOG has a section",
        "  [ ] chk-2  live version equals the tag",
    ]


def test_release_show_of_a_card_that_is_no_release(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    answer(fake, "GET", TASK, {"id": "tsk-0004", "kind": "task"})
    assert cli.main(["release", "show", "tsk-0004"]) == cli.EXIT_ERROR
    assert "not a release card" in capsys.readouterr().err


def test_release_show_with_none_in_flight(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    answer(fake, "GET", TASKS, {"items": [release_card("tsk-0003", "done")], "next_cursor": None})
    assert cli.main(["release", "show"]) == cli.EXIT_ERROR
    assert "no release is in flight" in capsys.readouterr().err


def test_release_tick_and_undo(joined: Path, fake: fakehub.FakeHub) -> None:
    path = f"{TASKS}/tsk-0010/checklist/chk-2"
    answer(fake, "POST", path, release_card())
    assert cli.main(["release", "tick", "chk-2", "--release", "tsk-0010"]) == cli.EXIT_OK
    assert (last(fake).path, last(fake).json()) == (path, {"done": True})
    assert cli.main(["release", "tick", "chk-2", "--release", "tsk-0010", "--undo"]) == 0
    assert last(fake).json() == {"done": False}


def test_release_tick_defaults_to_the_release_in_flight(
    joined: Path, fake: fakehub.FakeHub
) -> None:
    answer(fake, "GET", TASKS, {"items": [release_card("tsk-0010")], "next_cursor": None})
    answer(fake, "POST", f"{TASKS}/tsk-0010/checklist/chk-2", release_card())
    assert cli.main(["release", "tick", "chk-2"]) == cli.EXIT_OK
    assert last(fake).path == f"{TASKS}/tsk-0010/checklist/chk-2"


# --- --json on the older commands ------------------------------------------------------------


def test_ask_json_prints_the_request(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    request = {"id": "req-0013", "class": "info", "status": "open"}
    answer(fake, "POST", "/api/v1/projects/maity/requests", request, status=201)
    assert cli.main(["ask", "Which port?", "--to", "human", "--class", "info", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == request


# --- invalid answers -------------------------------------------------------------------------


def test_invalid_prints_field_reasons_but_no_values(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    fields = {
        "priority": "urgent_needs_requests_answer",
        "to": "not_a_member",
        "title": "value 'Tag 0.2.0 now?' is too long",
    }
    refusal = {"error": {"code": "invalid", "message": "the request does not validate",
                         "details": {"fields": fields}}}  # fmt: skip
    answer(fake, "POST", "/api/v1/projects/maity/requests", refusal, status=400)
    argv = ["ask", "Tag 0.2.0 now?", "--to", "agt-x", "--class", "info", "--priority", "urgent"]
    assert cli.main(argv) == cli.EXIT_ERROR
    err = capsys.readouterr().err
    assert "invalid: the request does not validate" in err
    assert "\n  priority: urgent_needs_requests_answer" in err
    assert "\n  to: not_a_member" in err
    assert "\n  title: (reason not shown)" in err
    assert "Tag 0.2.0" not in err


def test_other_errors_print_no_field_list(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    details = {"fields": {"a": "b"}}
    refusal = {"error": {"code": "forbidden", "message": "not yours", "details": details}}
    answer(fake, "POST", f"{TASK}/claim", refusal, status=403)
    assert cli.main(["claim", "tsk-0004"]) == cli.EXIT_ERROR
    assert "  a: b" not in capsys.readouterr().err
