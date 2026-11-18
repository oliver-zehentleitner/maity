"""One row never stops the outbox; header text is one line; names refuse control and
line-break characters (docs/api.md §1.7, §2.7.4, §16.2, §18.5)."""

from __future__ import annotations

import logging
import unicodedata
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import Engine, insert, select, update

from maity_hub import clock, invitation_mail, orgs, registration_accounts
from maity_hub import instance_settings as store
from maity_hub import tables as t
from maity_hub.mail import headers, outbox, smtp
from maity_hub.models import one_line
from tests import flow
from tests.conftest import ClientFactory
from tests.smtpfake import FakeSmtp, Script
from tests.test_mail_outbox import mail_env

# One of each kind the cleaning covers: C0 (line breaks and others), U+007F, C1 (U+0085
# among them), and the Unicode line and paragraph separators.
FOLDED = [
    "\r",
    "\n",
    "\r\n",
    "\t",
    "\x00",
    "\x0b",
    "\x0c",
    "\x1c",
    "\x1d",
    "\x1e",
    "\x1f",
    "\x7f",
    "\x80",
    "\x85",
    "\x9f",
    " ",
    " ",
]
REFUSED = frozenset({"Cc", "Zl", "Zp"})


def _every_refused_character() -> list[str]:
    return [chr(c) for c in range(0x110000) if unicodedata.category(chr(c)) in REFUSED]


# --- header cleaning -------------------------------------------------------------------


@pytest.mark.parametrize("bad", FOLDED, ids=[f"U+{ord(b[0]):04X}" for b in FOLDED])
def test_clean_folds_each_control_and_line_break_into_one_space(bad: str) -> None:
    assert headers.clean(f"a{bad}b") == "a b"
    assert headers.clean(f"a{bad}{bad}b") == "a b"  # a run is one space
    assert not headers.printable(f"a{bad}b", 10)


def test_clean_covers_every_character_of_categories_cc_zl_zp_and_nothing_else() -> None:
    every = _every_refused_character()
    assert len(every) == 67  # 65 Cc, one Zl, one Zp
    for ch in every:
        assert headers.clean(ch) == " ", hex(ord(ch))
    kept = "Zoë ‍👩‍💻 名前 ­ "  # format characters and spaces are no line break
    assert headers.clean(kept) == kept


@pytest.mark.parametrize("bad", FOLDED, ids=[f"U+{ord(b[0]):04X}" for b in FOLDED])
def test_a_message_builds_whatever_its_subject_and_sender_name_hold(bad: str) -> None:
    mail = headers.message(
        sender="maity@example.org",
        sender_name=f"Mai{bad}ty",
        to="me@example.org",
        subject=f"[Maity] Evil{bad}Bcc: other@example.org",
        body="b\n",
    )
    raw = mail.as_bytes()
    assert b"\nBcc:" not in raw and b"\rBcc:" not in raw
    assert mail["Bcc"] is None
    assert "\n" not in str(mail["Subject"]) and "\x85" not in str(mail["Subject"])


def test_the_invitation_subject_is_one_line() -> None:
    subject, _body = invitation_mail.text(
        inviter="Ann Bcc: x@example.org",
        project_name="Evil\x85Bcc: x@example.org",
        full_name="ann/evil",
        public_url="https://maity.example",
        trust="member",
        role="coder",
        note=None,
        url="https://maity.example/i/t",
        expires_at=clock.now(),
    )
    assert headers.clean(subject) == subject
    assert subject.startswith("[Maity] Ann Bcc: x@example[.]org invites you to Evil Bcc:")


def test_enqueue_stores_the_subject_on_one_line(migrated: Engine) -> None:
    with migrated.begin() as conn:
        outbox.enqueue(conn, kind="security", to="me@example.org", subject="a\x85b c", body="b\n")
        assert conn.execute(select(t.mail_outbox.c.subject)).scalar() == "a b c"


# --- the outbox survives a bad row ----------------------------------------------------


def _row(conn: Any, *, body: str = "b\n", subject: str = "s", **values: Any) -> int:
    """A row as it may stand in the table, written without `enqueue`'s cleaning."""
    now = clock.now()
    row = {
        "kind": "security",
        "recipient": "me@example.org",
        "subject": subject,
        "body": body,
        "headers": {},
        "created_at": now,
        "not_before": now,
        "attempts": 0,
        "status": "waiting",
        **values,
    }
    key = conn.execute(insert(t.mail_outbox).values(**row)).inserted_primary_key
    return int(key[0])


# A row that no message can be built from: a recipient no address may be (the hub only ever
# queues checked addresses, so this stands for any row a later bug could leave behind).
POISON = {"recipient": "me@ex\nample.org", "body": "secret-link https://maity.example/x\n"}


def _recording(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    """`smtp.send` replaced: every mail is accepted and kept."""
    sent: list[Any] = []

    def fake(_resolved: Any, mail: Any) -> smtp.Outcome:
        sent.append(mail)
        return smtp.Outcome(ok=True, stage=None, smtp_code=None, detail=None, at=clock.now())

    monkeypatch.setattr(smtp, "send", fake)
    return sent


def test_a_row_that_cannot_be_built_is_failed_and_the_good_rows_go_out(
    migrated: Engine, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent = _recording(monkeypatch)
    with migrated.begin() as conn:
        store.put(conn, "mail.security_max_per_hour", 2, None)
        first = _row(conn, subject="first")
        poison = _row(conn, headers={"List-Unsubscribe": "<https://x/y>"}, **POISON)
        last = _row(conn, subject="last")
    with caplog.at_level(logging.ERROR, logger="maity_hub.mail.outbox"):
        assert outbox.send_due(migrated, mail_env().mail, None) == 2
    assert [str(m["Subject"]) for m in sent] == ["first", "last"]
    with migrated.begin() as conn:
        rows = {r.id: r for r in conn.execute(select(t.mail_outbox)).all()}
        budget = conn.execute(select(t.mail_budget.c.admitted)).scalar_one()
        outcomes = sorted(conn.execute(select(t.mail_delivery.c.outcome)).scalars())
    assert rows[first].status == "sent" and rows[last].status == "sent"
    assert rows[poison].status == "failed"
    assert (rows[poison].body, rows[poison].headers) == ("", {})
    # The row took no place in the budget: both good mails fit into a budget of two.
    assert budget == 2
    assert outcomes == ["failed", "sent", "sent"]
    # Logged by id and kind, never with its text, address or headers.
    assert f"row {poison} (security)" in caplog.text
    assert "secret-link" not in caplog.text and "example" not in caplog.text
    # It does not come back on the next pass.
    later = clock.now() + timedelta(minutes=10)
    clock.set_source(lambda: later)
    assert outbox.send_due(migrated, mail_env().mail, None) == 0
    assert len(sent) == 2


def test_a_row_whose_sending_raises_is_failed_and_the_pass_goes_on(
    migrated: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    with migrated.begin() as conn:
        bad = _row(conn, subject="breaks")
        good = _row(conn)
    sent: list[str] = []

    def fake(_resolved: Any, mail: Any) -> smtp.Outcome:
        if mail["Subject"] == "breaks":
            raise RuntimeError("unexpected")
        sent.append(str(mail["Subject"]))
        return smtp.Outcome(ok=True, stage=None, smtp_code=None, detail=None, at=clock.now())

    monkeypatch.setattr(smtp, "send", fake)
    assert outbox.send_due(migrated, mail_env().mail, None) == 1
    with migrated.begin() as conn:
        status = dict(conn.execute(select(t.mail_outbox.c.id, t.mail_outbox.c.status)).all())
    assert status == {bad: "failed", good: "sent"} and sent == ["s"]


def test_a_row_left_in_sending_before_the_fix_is_taken_again_and_sent(
    migrated: Engine,
) -> None:
    """No migration: a claim lapses after two minutes, and the next pass builds the row under
    the cleaning, so a subject stored with a line break goes out on one line."""
    server = FakeSmtp(Script())
    try:
        with migrated.begin() as conn:
            stuck = _row(
                conn,
                subject="[Maity] Evil\x85Bcc: x@example.org",
                status="sending",
                not_before=clock.now() - timedelta(minutes=1),
            )
            unbuildable = _row(
                conn,
                **POISON,
                status="sending",
                not_before=clock.now() - timedelta(minutes=1),
            )
        assert outbox.send_due(migrated, mail_env(server.port).mail, None) == 1
        with migrated.begin() as conn:
            status = dict(conn.execute(select(t.mail_outbox.c.id, t.mail_outbox.c.status)).all())
        assert status == {stuck: "sent", unbuildable: "failed"}
        assert b"Subject: [Maity] Evil Bcc: x@example.org" in server.record.data
        assert b"\nBcc:" not in server.record.data
    finally:
        server.close()


def test_a_database_failure_still_ends_the_pass(
    migrated: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sqlalchemy.exc import OperationalError

    with migrated.begin() as conn:
        _row(conn)

    def broken(_conn: Any, _row_id: int) -> bool:
        raise OperationalError("select", {}, Exception("gone"))

    monkeypatch.setattr(outbox, "_claim", broken)
    with pytest.raises(OperationalError):
        outbox.send_due(migrated, mail_env(1).mail, None)
    with migrated.begin() as conn:
        assert conn.execute(select(t.mail_outbox.c.status)).scalar() == "waiting"


def test_a_lapsed_unbuildable_row_is_not_admitted_again(migrated: Engine) -> None:
    with migrated.begin() as conn:
        store.put(conn, "mail.security_max_per_hour", 1, None)
        _row(conn, **POISON)
        conn.execute(update(t.mail_outbox).values(not_before=clock.now()))
    assert outbox.send_due(migrated, mail_env(1).mail, None) == 0
    with migrated.begin() as conn:
        assert conn.execute(select(t.mail_budget)).first() is None


# --- names ----------------------------------------------------------------------------


def test_one_line_refuses_every_character_of_cc_zl_zp() -> None:
    for ch in _every_refused_character():
        assert not one_line(f"a{ch}b"), hex(ord(ch))
    assert one_line("Zoë ‍👩‍💻 名前")


@pytest.mark.parametrize("bad", ["\x85", " ", " ", "\x9f", "\n", "\x07"])
def test_a_project_name_refuses_control_and_line_break_characters(
    make_client: ClientFactory, migrated: Engine, bad: str
) -> None:
    owner = flow.human(make_client, migrated)
    refused = owner.post("/projects", {"slug": "evil", "name": f"Evil{bad}Bcc: x@example.org"})
    assert refused.status_code == 400, refused.text
    assert refused.json()["error"]["details"]["fields"] == {"name": "control_character"}
    flow.project(owner, "maity")
    patched = owner.patch("/projects/maintainer/maity", {"name": f"Maity{bad}x"})
    assert patched.status_code == 400, patched.text
    assert patched.json()["error"]["details"]["fields"] == {"name": "control_character"}
    fine = owner.patch("/projects/maintainer/maity", {"name": "Maity ‍👩‍💻"})
    assert fine.status_code == 200, fine.text


def test_an_agent_display_name_refuses_a_line_break(
    make_client: ClientFactory, migrated: Engine
) -> None:
    owner = flow.human(make_client, migrated)
    refused = owner.post("/agents", {"handle": "evil", "display_name": "Evil\x85x"})
    assert refused.status_code == 400, refused.text
    assert refused.json()["error"]["details"]["fields"] == {"display_name": "control_character"}
    made = owner.post("/agents", {"handle": "fine", "display_name": "Fine"})
    assert made.status_code in (200, 201), made.text
    patched = owner.patch(f"/agents/{made.json()['id']}", {"display_name": "Fine x"})
    assert patched.status_code == 400, patched.text
    assert patched.json()["error"]["details"]["fields"] == {"display_name": "control_character"}


@pytest.mark.parametrize("bad", ["\x85", "\u2028", "\u2029", "\n"])
def test_a_join_that_creates_an_agent_refuses_a_line_break_in_its_display_name(
    make_client: ClientFactory, migrated: Engine, bad: str
) -> None:
    owner = flow.human(make_client, migrated)
    flow.project(owner, "maity")
    refused = owner.post(
        "/projects/maintainer/maity/joins",
        {"agent": {"handle": "evil", "display_name": f"Evil{bad}x"}, "trust": "member"},
    )
    assert refused.status_code == 400, refused.text
    assert refused.json()["error"]["details"]["fields"] == {
        "agent.display_name": "control_character"
    }
    with migrated.begin() as conn:
        assert conn.execute(select(t.agent_profile)).first() is None


def test_creating_a_profile_refuses_a_line_break_whichever_body_carried_it(
    make_client: ClientFactory, migrated: Engine
) -> None:
    from maity_hub.errors import ApiError
    from maity_hub.routes.agents import create_profile

    owner = flow.human(make_client, migrated)
    with migrated.begin() as conn, pytest.raises(ApiError) as refused:
        create_profile(conn, owner.id, "evil", "Evil\x85x", None)
    assert (refused.value.code, refused.value.details) == (
        "invalid",
        {"fields": {"display_name": "control_character"}},
    )


def test_human_and_organisation_display_names_refuse_c1_and_unicode_line_breaks(
    migrated: Engine,
) -> None:
    for bad in ("\x85", " ", " ", "\x80"):
        assert not orgs.display_name_ok(f"Team{bad}x")
        with migrated.begin() as conn:
            assert registration_accounts.check_names(conn, "free-name", f"Ann{bad}x") == {
                "display_name": "invalid"
            }
    assert orgs.display_name_ok("Team ‍👩‍💻")


def test_the_invitation_subject_is_cut_like_every_subject() -> None:
    subject, _body = invitation_mail.text(
        inviter="Ann " + "a" * 200,
        project_name="see evil.example " + "p" * 200,
        full_name="ann/evil",
        public_url="https://maity.example",
        trust="member",
        role="coder",
        note=None,
        url="https://maity.example/i/t",
        expires_at=clock.now(),
    )
    assert len(subject) <= 120 and subject.endswith("…")
