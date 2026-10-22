"""The convenience commands: each one call, signed, with an idempotency key on writes."""

from __future__ import annotations

import json
import urllib.parse
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


# --- review round: refs, ids, empty values, retries ----------------------------------------


def test_checkpoint_outside_a_work_tree_is_an_error(
    joined: Path, fake: fakehub.FakeHub, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MAITY_STATE_DIR", str(joined))
    elsewhere = tmp_path / "not-a-clone"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    assert cli.main(["checkpoint", "tsk-0004", "-m", "a", "--next", "b"]) == cli.EXIT_ERROR
    assert fake.signed() == []


def test_checkpoint_on_an_unborn_head_is_an_error(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    git(joined.parent.parent, "switch", "--quiet", "--orphan", "fresh")
    assert cli.main(["checkpoint", "tsk-0004", "-m", "a", "--next", "b"]) == cli.EXIT_ERROR
    assert "no commit yet" in capsys.readouterr().err
    assert fake.signed() == []


@pytest.mark.parametrize("bad", ["", " ", ".", ".."])
@pytest.mark.parametrize(
    "argv",
    [
        ["claim", "{}"],
        ["unclaim", "{}"],
        ["checkpoint", "{}", "-m", "a", "--next", "b"],
        ["answer", "{}", "--reply", "o1"],
        ["release", "show", "{}"],
        ["release", "tick", "{}"],
        ["release", "tick", "chk-1", "--release", "{}"],
        ["say", "all", "hi", "--type", "notice", "--task", "{}"],
        ["report", "--task", "{}", "--summary", "s"],
    ],
)
def test_empty_and_dot_ids_are_usage_errors(argv: list[str], bad: str) -> None:
    with pytest.raises(SystemExit) as exc:
        cli.build_parser().parse_args([bad if a == "{}" else a for a in argv])
    assert exc.value.code == cli.EXIT_USAGE


def test_a_credential_shaped_id_is_not_sent(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["claim", fakehub.CREDENTIAL]) == cli.EXIT_ERROR
    assert fake.signed() == []
    assert fakehub.SECRET not in capsys.readouterr().err


def test_an_empty_reason_is_a_usage_error(joined: Path, fake: fakehub.FakeHub) -> None:
    assert cli.main(["claim", "tsk-0004", "--reason", ""]) == cli.EXIT_USAGE
    assert fake.signed() == []


def test_message_indentation_is_kept(joined: Path, fake: fakehub.FakeHub) -> None:
    answer(fake, "POST", "/api/v1/projects/maity/events", {"seq": 1})
    body = "    code block\n- item\n"
    assert cli.main(["say", "all", body, "--type", "notice"]) == cli.EXIT_OK
    assert last(fake).json()["body"] == body


def test_a_repeated_claim_of_an_own_card_succeeds(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    details = {"holder": "agt-b", "lease_until": "T2", "expired": False}
    refusal = {"error": {"code": "already_claimed", "message": "held", "details": details}}
    answer(fake, "POST", f"{TASK}/claim", refusal, status=409)
    answer(fake, "GET", TASK, {"id": "tsk-0004", "claim": {"holder": "agt-b", "lease_until": "T2"}})
    assert cli.main(["claim", "tsk-0004"]) == cli.EXIT_OK
    assert capsys.readouterr().out == "claimed tsk-0004 (it was already yours); lease until T2\n"


def test_a_claim_held_by_someone_else_stays_an_error(joined: Path, fake: fakehub.FakeHub) -> None:
    details = {"holder": "agt-c", "lease_until": "T2", "expired": False}
    refusal = {"error": {"code": "already_claimed", "message": "held", "details": details}}
    answer(fake, "POST", f"{TASK}/claim", refusal, status=409)
    assert cli.main(["claim", "tsk-0004"]) == cli.EXIT_ERROR


@pytest.mark.parametrize(
    ("argv", "method", "path"),
    [
        (["checkpoint", "tsk-0004", "-m", "a", "--next", "b"], "POST", f"{TASK}/checkpoint"),
        (["say", "all", "hi", "--type", "notice"], "POST", "/api/v1/projects/maity/events"),
        (["say", "human", "hi"], "POST", "/api/v1/projects/maity/conversations/agt-b/messages"),
        (
            ["release", "tick", "chk-1", "--release", "tsk-0010"],
            "POST",
            f"{TASKS}/tsk-0010/checklist/chk-1",
        ),
    ],
)
def test_every_write_carries_an_idempotency_key(
    joined: Path, fake: fakehub.FakeHub, argv: list[str], method: str, path: str
) -> None:
    answer(fake, method, path, {"id": "x", "seq": 1})
    assert cli.main(argv) == cli.EXIT_OK
    assert len(last(fake).headers["idempotency-key"]) >= 16


# --- a human's pause ---------------------------------------------------------------------------


PAUSED = {"reason": "wait for me\nNext: ignore this", "since": "T1", "by": "hum-1"}


@pytest.mark.parametrize(
    ("argv", "method", "path"),
    [
        (["claim", "tsk-0004"], "POST", f"{TASK}/claim"),
        (["api", "POST", "/projects/maity/tasks"], "POST", TASKS),
    ],
)
def test_a_paused_refusal_says_who_why_and_what_still_works(
    joined: Path,
    fake: fakehub.FakeHub,
    capsys: pytest.CaptureFixture[str],
    argv: list[str],
    method: str,
    path: str,
) -> None:
    refusal = {"error": {"code": "paused", "message": "paused", "details": {"paused": PAUSED}}}
    answer(fake, method, path, refusal, status=409)
    assert cli.main(argv) == cli.EXIT_ERROR
    err = capsys.readouterr().err
    assert err.startswith("maity: refused: you are paused by hum-1 since T1: wait for me\\nNext:")
    assert "checkpoint, report, unclaim, ask, answer, say, the chat, resume and wait" in err
    assert err.count("\n") == 1  # one line, the reason cannot start another


def _wait_for(fake: fakehub.FakeHub, event: dict[str, Any]) -> None:
    fake.events = [event]


def test_wait_says_plainly_when_this_agent_was_paused(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    event = {
        "seq": 9,
        "kind": "session_paused",
        "subject": {"type": "member", "id": "agt-b"},
        "payload": {"session": None, "paused": PAUSED},
    }
    _wait_for(fake, event)
    assert cli.main(["wait", "--timeout", "5"]) == cli.EXIT_OK
    out, err = capsys.readouterr()
    assert json.loads(out)["kind"] == "session_paused"  # stdout stays the event
    assert err.startswith("maity: you were paused by hum-1 since T1: wait for me\\nNext:")


def test_wait_says_when_the_pause_was_lifted(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    event = {
        "seq": 9,
        "kind": "session_paused",
        "subject": {"type": "member", "id": "agt-b"},
        "payload": {"session": None, "paused": None},
    }
    _wait_for(fake, event)
    assert cli.main(["wait", "--timeout", "5"]) == cli.EXIT_OK
    assert capsys.readouterr().err == "maity: your pause was lifted; you can take new work again.\n"


def test_wait_is_quiet_about_someone_elses_pause(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    event = {
        "seq": 9,
        "kind": "session_paused",
        "subject": {"type": "member", "id": "agt-c"},
        "payload": {"session": None, "paused": PAUSED},
    }
    _wait_for(fake, event)
    assert cli.main(["wait", "--timeout", "5"]) == cli.EXIT_OK
    assert capsys.readouterr().err == ""


def test_report_no_code_reads_and_sends_no_git_facts(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:  # fmt: skip
    from maity import gitfacts

    def untouched(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("no git facts with --no-code")

    monkeypatch.setattr(gitfacts, "collect", untouched)
    fake.routes[("POST", "/api/v1/projects/maity/tasks/tsk-7/report")] = lambda seen: (
        200, {"id": "tsk-7", "status": "review"}
    )  # fmt: skip
    (joined.parent.parent / "dirty.txt").write_text("uncommitted")
    code = cli.main(["report", "--task", "tsk-7", "--summary", "The draft: …", "--no-code"])
    assert code == cli.EXIT_OK, capsys.readouterr().err
    body = fake.signed()[-1].json()
    assert body["code"] is False and body["pr_status"] == "none"
    assert all(body[k] is None for k in ("head", "branch", "upstream", "remote_head", "pr"))
    assert "(no code)" in capsys.readouterr().out


def test_wait_batch_prints_every_pending_event_and_moves_the_cursor_past_them(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    fake.events += [{"seq": n, "kind": "task_claimed"} for n in (11, 12, 13)]
    assert cli.main(["wait", "--timeout", "5", "--batch"]) == cli.EXIT_OK
    printed = json.loads(capsys.readouterr().out)
    assert [e["seq"] for e in printed] == [11, 12, 13]
    assert state.load_state(joined)["cursor"] == 13


def test_wait_without_batch_still_prints_one_event(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    fake.events += [{"seq": n, "kind": "task_claimed"} for n in (11, 12)]
    assert cli.main(["wait", "--timeout", "5"]) == cli.EXIT_OK
    assert json.loads(capsys.readouterr().out)["seq"] == 11
    assert state.load_state(joined)["cursor"] == 11


def test_checkpoint_warns_on_a_detached_head(
    joined: Path, clone: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    fake.routes[("POST", "/api/v1/projects/maity/tasks/tsk-1/checkpoint")] = lambda seen: (
        200, {"id": "tsk-1"}
    )  # fmt: skip
    git(clone, "checkout", "-q", "--detach")
    assert cli.main(["checkpoint", "tsk-1", "-m", "a", "--next", "b"]) == cli.EXIT_OK
    assert "HEAD is detached" in capsys.readouterr().err
    assert "branch" not in fake.signed()[-1].json()


def test_checkpoint_warns_when_the_branch_changed(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    fake.routes[("GET", "/api/v1/projects/maity/tasks/tsk-1")] = lambda seen: (
        200, {"id": "tsk-1", "checkpoint": {"branch": "agent-b/other"}}
    )  # fmt: skip
    fake.routes[("POST", "/api/v1/projects/maity/tasks/tsk-1/checkpoint")] = lambda seen: (
        200, {"id": "tsk-1"}
    )  # fmt: skip
    assert cli.main(["checkpoint", "tsk-1", "-m", "a", "--next", "b"]) == cli.EXIT_OK
    assert "last checkpoint was on agent-b/other" in capsys.readouterr().err


def test_checkpoint_no_code_sends_no_git_facts(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    fake.routes[("POST", "/api/v1/projects/maity/tasks/tsk-1/checkpoint")] = lambda seen: (
        200, {"id": "tsk-1"}
    )  # fmt: skip
    code = cli.main(["checkpoint", "tsk-1", "-m", "draft", "--next", "review", "--no-code"])
    assert code == cli.EXIT_OK
    assert fake.signed()[-1].json() == {"last_step": "draft", "next_step": "review"}


def test_join_offers_the_pointer_block_instead_of_writing_it(
    clone: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    from maity import pointer

    assert cli.main(["join", f"{fake.url}/j/{fakehub.TOKEN}", "--code", fakehub.CODE]) == 0
    assert not (clone / "AGENTS.md").exists()
    assert pointer.BEGIN in capsys.readouterr().err


def test_api_accepts_a_query_in_the_path(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    fake.routes[("GET", "/api/v1/projects/maity/tasks")] = lambda seen: (200, {"items": []})
    code = cli.main(
        ["api", "GET", "/projects/maity/tasks?state=open&after=28", "--query", "limit=5"]
    )
    assert code == cli.EXIT_OK, capsys.readouterr().err
    seen = fake.signed()[-1]
    assert seen.path == "/api/v1/projects/maity/tasks"
    assert dict(urllib.parse.parse_qsl(seen.query)) == {
        "state": "open",
        "after": "28",
        "limit": "5",
    }


def test_api_refuses_a_fragment(joined: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["api", "GET", "/projects/maity/tasks#x"]) == cli.EXIT_ERROR
    assert "fragment" in capsys.readouterr().err


def test_say_to_your_own_humans_id_without_a_type_is_the_chat(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    fake.routes[("POST", "/api/v1/projects/maity/conversations/agt-b/messages")] = lambda seen: (
        201, {"seq": 9}
    )  # fmt: skip
    assert cli.main(["resume"]) == cli.EXIT_OK
    capsys.readouterr()
    assert cli.main(["say", "hum-1", "thanks, done"]) == cli.EXIT_OK
    sent = fake.signed()[-1]
    assert sent.path == "/api/v1/projects/maity/conversations/agt-b/messages"
    assert sent.json() == {"body": "thanks, done"}


def test_say_to_another_human_still_needs_a_type(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["resume"]) == cli.EXIT_OK
    capsys.readouterr()
    assert cli.main(["say", "hum-2", "hello"]) == cli.EXIT_USAGE
    assert "--type is required" in capsys.readouterr().err


def test_outside_a_clone_the_error_names_maity_state_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    with pytest.raises(state.StateError) as info:
        state.resolve_state_dir()
    assert "export MAITY_STATE_DIR=~/.local/state/maity/<agent-handle>" in str(info.value)


def test_wait_batch_over_the_cap_comes_in_two_calls_each_event_once(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    fake.events += [{"seq": n, "kind": "task_claimed"} for n in range(101, 171)]
    assert cli.main(["wait", "--timeout", "5", "--batch"]) == cli.EXIT_OK
    first = [e["seq"] for e in json.loads(capsys.readouterr().out)]
    assert first == list(range(101, 101 + cli.BATCH_MAX))
    assert state.load_state(joined)["cursor"] == first[-1]
    assert cli.main(["wait", "--timeout", "5", "--batch"]) == cli.EXIT_OK
    second = [e["seq"] for e in json.loads(capsys.readouterr().out)]
    assert second == list(range(101 + cli.BATCH_MAX, 171))


# --- placements and runners (§15.6) ----------------------------------------------------------

PLACEMENT = {
    "id": "plc-0003", "agent": {"id": "agt-f", "handle": "agent-f"},
    "runner": {"id": "rnr-0002", "name": "home"}, "harness": "claude-code",
    "mode": "interactive", "desired": "running", "reported_current": True,
    "reported": {"state": "running", "reason": None},
}  # fmt: skip


def placements(fake: fakehub.FakeHub) -> None:
    fake.routes[("GET", "/api/v1/projects/maity/placements")] = lambda seen: (
        200, {"items": [PLACEMENT]}
    )  # fmt: skip


def test_placement_list(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    placements(fake)
    assert cli.main(["placement", "list"]) == cli.EXIT_OK
    out = capsys.readouterr().out
    assert "plc-0003  agent-f on home  claude-code interactive  desired running, running" in out


def test_placement_start_resolves_the_handle_and_names_the_consent_request(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    fake.routes[("GET", "/api/v1/projects/maity/members")] = lambda seen: (
        200, {"items": [{"id": "agt-f", "handle": "agent-f"}]}
    )  # fmt: skip
    fake.routes[("POST", "/api/v1/projects/maity/placements")] = lambda seen: (
        201, {"id": "plc-0009", "approval": {"status": "pending", "request_id": "req-4"}}
    )  # fmt: skip
    code = cli.main(
        ["placement", "start", "agent-f", "--runner", "rnr-0002", "--tool", "codex",
         "--mode", "supervised", "--clone", "agent-f2", "--reason", "second pair of hands"]
    )  # fmt: skip
    assert code == cli.EXIT_OK, capsys.readouterr().err
    body = fake.signed()[-1].json()
    assert body == {
        "agent": {"id": "agt-f"}, "runner": "rnr-0002", "harness": "codex",
        "reason": "second pair of hands", "mode": "supervised",
        "workspace": {"clone": "agent-f2"},
    }  # fmt: skip
    assert "waiting for consent (request req-4)" in capsys.readouterr().out


def test_placement_stop_by_handle_with_grace(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    placements(fake)
    fake.routes[("PATCH", "/api/v1/projects/maity/placements/plc-0003")] = lambda seen: (
        200, PLACEMENT
    )  # fmt: skip
    assert cli.main(["placement", "stop", "agent-f", "--grace", "60"]) == cli.EXIT_OK
    assert fake.signed()[-1].json() == {"desired": "stopped", "stop_grace_seconds": 60}


def test_placement_restart_by_id(joined: Path, fake: fakehub.FakeHub) -> None:
    placements(fake)
    fake.routes[("POST", "/api/v1/projects/maity/placements/plc-0003/restart")] = lambda seen: (
        200, PLACEMENT
    )  # fmt: skip
    assert cli.main(["placement", "restart", "plc-0003"]) == cli.EXIT_OK
    assert fake.signed()[-1].path.endswith("/plc-0003/restart")


def test_placement_for_an_unknown_agent(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    placements(fake)
    assert cli.main(["placement", "stop", "agent-z"]) == cli.EXIT_ERROR
    assert "no active placement agent-z" in capsys.readouterr().err


def test_an_agent_handle_list_is_not_a_subcommand(joined: Path, fake: fakehub.FakeHub) -> None:
    placements(fake)
    fake.routes[("PATCH", "/api/v1/projects/maity/placements/plc-0003")] = lambda seen: (
        200, PLACEMENT
    )  # fmt: skip
    listed = {**PLACEMENT, "agent": {"id": "agt-l", "handle": "list"}}
    fake.routes[("GET", "/api/v1/projects/maity/placements")] = lambda seen: (
        200, {"items": [listed]}
    )  # fmt: skip
    assert cli.main(["placement", "stop", "list"]) == cli.EXIT_OK


def test_runners(joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]) -> None:
    runner = {
        "id": "rnr-0002", "name": "home", "presence": "online",
        "capabilities": {"running": 1, "max_agents": 4, "harnesses": [
            {"id": "claude-code", "available": True}, {"id": "codex", "available": False}]},
    }  # fmt: skip
    fake.routes[("GET", "/api/v1/projects/maity/runners")] = lambda seen: (
        200, {"items": [{"runner": runner}]}
    )  # fmt: skip
    assert cli.main(["runners"]) == cli.EXIT_OK
    assert "rnr-0002  home  online  1/4 running  tools: claude-code" in capsys.readouterr().out


def test_an_exact_placement_id_wins_and_ambiguity_is_refused(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    decoy = {**PLACEMENT, "id": "plc-bbbb", "agent": {"id": "agt-x", "handle": "plc-aaaa"}}
    target = {**PLACEMENT, "id": "plc-aaaa", "agent": {"id": "agt-y", "handle": "y"}}
    fake.routes[("GET", "/api/v1/projects/maity/placements")] = lambda seen: (
        200, {"items": [decoy, target]}
    )  # fmt: skip
    fake.routes[("PATCH", "/api/v1/projects/maity/placements/plc-aaaa")] = lambda seen: (
        200, target
    )  # fmt: skip
    assert cli.main(["placement", "stop", "plc-aaaa"]) == cli.EXIT_OK
    assert fake.signed()[-1].path.endswith("/plc-aaaa")
    twins = [{**PLACEMENT, "id": f"plc-{n}", "agent": {"id": f"agt-{n}", "handle": "same"}}
             for n in (1, 2)]  # fmt: skip
    fake.routes[("GET", "/api/v1/projects/maity/placements")] = lambda seen: (
        200, {"items": twins}
    )  # fmt: skip
    capsys.readouterr()
    assert cli.main(["placement", "stop", "same"]) == cli.EXIT_ERROR
    assert "more than one active placement" in capsys.readouterr().err


def test_hub_ids_are_cleaned_and_must_be_strings(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    hostile = {**PLACEMENT, "id": "plc-1\x1b]52;c;evil\x07"}
    broken = {**PLACEMENT, "id": 7, "agent": {"id": "agt-7", "handle": "seven"}}
    fake.routes[("GET", "/api/v1/projects/maity/placements")] = lambda seen: (
        200, {"items": [hostile, broken]}
    )  # fmt: skip
    capsys.readouterr()
    assert cli.main(["placement", "list"]) == cli.EXIT_OK
    assert "\x1b" not in capsys.readouterr().out
    assert cli.main(["placement", "stop", "seven"]) == cli.EXIT_ERROR  # no crash on id 7


def test_placement_grace_is_range_checked(joined: Path) -> None:
    with pytest.raises(SystemExit):
        cli.main(["placement", "stop", "agent-f", "--grace", "901"])


def test_placement_restart_with_rejoin(joined: Path, fake: fakehub.FakeHub) -> None:
    placements(fake)
    fake.routes[("POST", "/api/v1/projects/maity/placements/plc-0003/restart")] = lambda seen: (
        200, PLACEMENT
    )  # fmt: skip
    assert cli.main(["placement", "restart", "agent-f", "--rejoin"]) == cli.EXIT_OK
    assert fake.signed()[-1].json() == {"rejoin": True}


def test_wait_keep_cursor_acknowledges_nothing(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    before = state.load_state(joined).get("cursor")
    fake.events.append({"seq": 21, "kind": "message"})
    assert cli.main(["wait", "--timeout", "5", "--keep-cursor"]) == cli.EXIT_OK
    assert json.loads(capsys.readouterr().out)["seq"] == 21
    assert state.load_state(joined).get("cursor") == before
