"""Trust × role on the CLI (§2.3): the proxy's bound go (`maity ask --action`, `--on-request`,
signed per §2.2), `maity answer --on-behalf-of`, role memory (§19.2) and trust and role where
the CLI prints members."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import fakehub
import pytest

from maity import cli, onboarding, sign

P = "/api/v1/projects/oliver/maity"
EMPTY_SHA = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
MEMBERS = {
    "items": [
        {"id": "agt-p", "handle": "proxy", "trust": "admin", "role": "proxy"},
        {"id": "hum-m", "handle": "maint", "trust": "owner", "role": "coder"},
    ]
}


# --- the signature (§2.2) ------------------------------------------------------------------------


def test_without_the_header_the_canonical_string_keeps_its_seven_lines() -> None:
    text = sign.canonical_string("POST", "/api/v1/x", "", "17", "n", b"")
    assert text.split("\n") == ["MAITY-HMAC-V1", "POST", "/api/v1/x", "", "17", "n", EMPTY_SHA]


def test_the_on_request_line_comes_before_the_body_hash_when_the_header_is_sent() -> None:
    text = sign.canonical_string("POST", "/api/v1/x", "", "17", "n", b"", "req-0091")
    assert text.split("\n") == [
        "MAITY-HMAC-V1", "POST", "/api/v1/x", "", "17", "n", "req-0091", EMPTY_SHA]  # fmt: skip


def test_sign_headers_sends_the_header_only_with_a_request() -> None:
    key = sign.SigningKey("crd-1", b"k" * 32)
    assert "Maity-On-Request" not in sign.sign_headers(key, "POST", "/api/v1/x", "", b"", 1)
    signed = sign.sign_headers(key, "POST", "/api/v1/x", "", b"", 1, "req-0091")
    assert signed["Maity-On-Request"] == "req-0091"
    plain = sign.sign_headers(key, "POST", "/api/v1/x", "", b"", 1)
    assert signed["Maity-Signature"] != plain["Maity-Signature"]


# --- --on-request ---------------------------------------------------------------------------------


def test_api_sends_the_go_signed_and_the_body_as_read(
    joined: Path, fake: fakehub.FakeHub, tmp_path: Path
) -> None:
    body = tmp_path / "body.json"
    body.write_bytes(b'{ "trust":  "guest" }\n')
    fake.routes[("PATCH", f"{P}/members/agt-b")] = lambda s: (200, {"id": "agt-b"})
    argv = ["api", "PATCH", "/projects/oliver/maity/members/agt-b", "--json", str(body),
            "--on-request", "req-0091"]  # fmt: skip
    assert cli.main(argv) == cli.EXIT_OK
    seen = fake.signed()[-1]  # the fake hub verified the signature over the extra line
    assert seen.headers["maity-on-request"] == "req-0091"
    assert seen.body == b'{ "trust":  "guest" }\n'
    assert seen.headers["content-type"] == "application/json"


def test_api_without_a_go_sends_neither_header_nor_raw_body(
    joined: Path, fake: fakehub.FakeHub, tmp_path: Path
) -> None:
    body = tmp_path / "body.json"
    body.write_text('{ "paused": true }')
    fake.routes[("PATCH", "/api/v1/me")] = lambda s: (200, {})
    assert cli.main(["api", "PATCH", "/me", "--json", str(body)]) == cli.EXIT_OK
    seen = fake.signed()[-1]
    assert "maity-on-request" not in seen.headers
    assert seen.body == b'{"paused":true}'


def test_reads_carry_no_go(joined: Path, fake: fakehub.FakeHub) -> None:
    fake.routes[("GET", f"{P}/members")] = lambda s: (200, MEMBERS)
    argv = ["api", "GET", "/projects/oliver/maity/members", "--on-request", "req-0091"]
    assert cli.main(argv) == cli.EXIT_OK
    assert "maity-on-request" not in fake.signed()[-1].headers


def test_a_command_with_admin_calls_takes_the_go(joined: Path, fake: fakehub.FakeHub) -> None:
    fake.routes[("POST", f"{P}/tasks")] = lambda s: (201, {"id": "tsk-9", "status": "open"})
    argv = ["task", "create", "Fix it", "--assign", "agt-b", "--on-request", "req-0091"]
    assert cli.main(argv) == cli.EXIT_OK
    assert fake.signed()[-1].headers["maity-on-request"] == "req-0091"


def test_the_go_is_not_kept_for_the_next_command(joined: Path, fake: fakehub.FakeHub) -> None:
    fake.routes[("POST", f"{P}/tasks")] = lambda s: (201, {"id": "tsk-9", "status": "open"})
    assert cli.main(["task", "create", "One", "--on-request", "req-0091"]) == cli.EXIT_OK
    assert cli.main(["task", "create", "Two"]) == cli.EXIT_OK
    assert "maity-on-request" not in fake.signed()[-1].headers


@pytest.mark.parametrize("value", ["", "req 1", "req-1\r\nX-Evil: 1", "r" * 65])
def test_a_go_that_is_no_request_id_is_refused(
    joined: Path, fake: fakehub.FakeHub, value: str
) -> None:
    with pytest.raises(SystemExit) as exc:
        cli.main(["api", "POST", "/x", "--on-request", value])
    assert exc.value.code == cli.EXIT_USAGE
    assert fake.signed() == []


# --- maity ask --action (§7) ----------------------------------------------------------------------


def _ask(fake: fakehub.FakeHub) -> None:
    fake.routes[("POST", f"{P}/requests")] = lambda s: (
        201, {"id": "req-0091", "class": "decision", "status": "open"})  # fmt: skip


def test_ask_action_sends_the_exact_call(
    joined: Path, fake: fakehub.FakeHub, tmp_path: Path
) -> None:
    _ask(fake)
    body = tmp_path / "body.json"
    body.write_bytes(b'{ "trust":  "guest" }\n')
    argv = ["ask", "Make agent-b a guest?", "--to", "owner", "--class", "decision",
            "--action", "patch /api/v1/projects/oliver/maity/members/agt-b?b=2&a=x%20y",
            "--action-body", str(body)]  # fmt: skip
    assert cli.main(argv) == cli.EXIT_OK
    assert fake.signed()[-1].json()["action"] == {
        "method": "PATCH",
        "path": "/projects/oliver/maity/members/agt-b",
        "query": "a=x%20y&b=2",  # as `maity api --query` signs and sends it
        "body": '{ "trust":  "guest" }\n',
    }


def test_ask_action_without_body_or_query_sends_null(joined: Path, fake: fakehub.FakeHub) -> None:
    _ask(fake)
    argv = ["ask", "Remove agent-b?", "--to", "owner", "--class", "consent",
            "--action", "DELETE /projects/oliver/maity/members/agt-b"]  # fmt: skip
    assert cli.main(argv) == cli.EXIT_OK
    action = fake.signed()[-1].json()["action"]
    assert action == {"method": "DELETE", "path": "/projects/oliver/maity/members/agt-b",
                      "query": None, "body": None}  # fmt: skip


@pytest.mark.parametrize(
    "extra",
    [
        ["--action", "GET /projects/oliver/maity/members"],
        ["--action", "PATCH projects/oliver/maity"],
        ["--action", "PATCH"],
        ["--action", "PATCH /a#b"],
        ["--action-body", "body.json"],
        ["--action", "PATCH /x", "--action-body", "missing.json"],
        ["--action", "PATCH /x", "--action-body", "not-json.txt"],
        ["--action", "PATCH /x", "--action-body", "big.json"],
    ],
)
def test_ask_action_is_checked_before_sending(
    joined: Path, fake: fakehub.FakeHub, extra: list[str], monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:  # fmt: skip
    monkeypatch.chdir(tmp_path)
    (tmp_path / "body.json").write_text("{}")
    (tmp_path / "not-json.txt").write_text("trust: guest")
    (tmp_path / "big.json").write_text(json.dumps({"x": "y" * (64 * 1024)}))
    argv = ["ask", "Go?", "--to", "owner", "--class", "decision", *extra]
    assert cli.main(argv) == cli.EXIT_USAGE
    assert fake.signed() == []


# --- maity answer --on-behalf-of ------------------------------------------------------------------


def test_answer_on_behalf_of_names_the_owner_by_id(joined: Path, fake: fakehub.FakeHub) -> None:
    fake.routes[("GET", f"{P}/members")] = lambda s: (200, MEMBERS)
    fake.routes[("POST", f"{P}/requests/req-0012/answer")] = lambda s: (200, {"status": "answered"})
    argv = ["answer", "req-0012", "--reply", "o1", "--on-behalf-of", "maint"]
    assert cli.main(argv) == cli.EXIT_OK
    assert fake.signed()[-1].json() == {"reply_id": "o1", "on_behalf_of": "hum-m"}


def test_answer_without_on_behalf_of_reads_no_members(joined: Path, fake: fakehub.FakeHub) -> None:
    fake.routes[("POST", f"{P}/requests/req-0012/answer")] = lambda s: (200, {"status": "answered"})
    assert cli.main(["answer", "req-0012", "--text", "yes"]) == cli.EXIT_OK
    assert [s.method for s in fake.signed()] == ["POST"]
    assert fake.signed()[-1].json() == {"text": "yes"}


# --- say and ask to trust tokens ------------------------------------------------------------------


def test_say_and_ask_pass_trust_tokens_through(joined: Path, fake: fakehub.FakeHub) -> None:
    fake.routes[("POST", f"{P}/events")] = lambda s: (201, {"seq": 7})
    _ask(fake)
    assert cli.main(["say", "trust:admin", "CI is red", "--type", "blocker"]) == cli.EXIT_OK
    assert fake.signed()[-1].json()["to"] == "trust:admin"
    assert cli.main(["ask", "Go?", "--to", "trust:owner", "--class", "info"]) == cli.EXIT_OK
    assert fake.signed()[-1].json()["to"] == "trust:owner"


# --- role memory (§19.2) --------------------------------------------------------------------------

ROLE_ENTRY: dict[str, Any] = {
    "id": "mem-0060", "store": "role", "role": "reviewer", "member_id": None,
    "text": "Read the migration first.", "tags": [],
    "by": {"kind": "agent", "member_id": "agt-r", "instance": "x1", "handle": "review"},
    "confirmed_by": None, "request_id": None, "created_at": "2026-10-27T10:00:00Z",
    "deleted": None,
}  # fmt: skip


def test_memory_role_lists_the_role_store(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    fake.routes[("GET", f"{P}/memory")] = lambda s: (
        200, {"items": [ROLE_ENTRY], "next_cursor": None})  # fmt: skip
    assert cli.main(["memory", "--role"]) == cli.EXIT_OK
    assert "store=role" in fake.signed()[-1].query
    out = capsys.readouterr().out
    assert "Role memory (reviewer), review#x1, 2026-10-27  [mem-0060]" in out
    assert "> Read the migration first." in out


def test_memory_add_role(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    fake.routes[("POST", f"{P}/memory")] = lambda s: (201, ROLE_ENTRY)
    assert cli.main(["memory", "add", "Read the migration first.", "--role"]) == cli.EXIT_OK
    assert fake.signed()[-1].json() == {"store": "role", "text": "Read the migration first."}
    assert "added mem-0060 to the memory of reviewer" in capsys.readouterr().out


@pytest.mark.parametrize(
    "argv",
    [
        ["memory", "add", "x", "--role", "--community"],
        ["memory", "add", "--soul", "soul.md", "--reason", "r", "--role"],
        ["memory", "--role", "add", "x"],
    ],
)
def test_memory_role_flags_are_checked(
    joined: Path, fake: fakehub.FakeHub, argv: list[str]
) -> None:
    assert cli.main(argv) == cli.EXIT_USAGE
    assert fake.signed() == []


# --- trust and role where members are printed ----------------------------------------------------


def _packet(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "me": {"member_id": "agt-b", "handle": "agent-b"},
        "membership": {"trust": "member", "role": "reviewer", "reports_to": "agt-a"},
        "peers": [
            {"member_id": "agt-a", "handle": "agent-a", "trust": "admin", "role": "coder",
             "presence": "online"},
            {"member_id": "hum-1", "handle": "maint", "trust": "owner", "role": "coder",
             "presence": "away"},
        ],
    }  # fmt: skip
    data.update(overrides)
    return data


def test_resume_shows_trust_and_role() -> None:
    text = onboarding.render(_packet())
    assert "Trust: member, role: reviewer\n" in text and "Your lead: @agent-a\n" in text
    assert "agent-a [agt-a] (admin coder, online)" in text
    assert "maint [hum-1] (owner coder, away)" in text


def test_a_trust_the_hub_left_out_shows_as_a_question_mark() -> None:
    text = onboarding.render(_packet(membership={"role": "reviewer", "reports_to": "agt-a"}))
    assert "Trust: ?, role: reviewer" in text and "None" not in text


def test_resume_shows_the_role_memory() -> None:
    memory = {"role": {"role": "reviewer", "items": [ROLE_ENTRY], "total": 9, "truncated": True}}
    text = onboarding.render(_packet(memory=memory))
    assert "Role memory (reviewer), review#x1" in text
    assert "More role memory (9 in all): maity memory --role" in text


@pytest.mark.parametrize(
    ("membership", "admin"),
    [
        ({"trust": "admin", "role": "coder"}, True),
        ({"trust": "admin", "role": "proxy"}, False),  # never in the admin team
        ({"trust": "member", "role": "coder"}, False),
        ({"role": "admin"}, False),  # no trust: never admin
        ({"trust": "member", "role": "admin"}, False),
    ],
)
def test_is_admin_reads_the_trust(membership: dict[str, Any], admin: bool) -> None:
    assert onboarding.is_admin({"membership": membership}) is admin
