"""Deleting your own account (docs/api.md §2.9): the request with its proof and step-up,
the refusals, the mailed link and its page, every withdrawal, and what the deletion does,
in one transaction."""

from __future__ import annotations

import contextvars
import re
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import Engine, func, insert, select, update
from sqlalchemy.exc import IntegrityError

from maity_hub import account_deletion, clock
from maity_hub import tables as t
from maity_hub.events import lock_project
from maity_hub.middleware import _TOKEN_PATHS
from tests import factory, flow
from tests.conftest import ClientFactory
from tests.test_address_step_up import confirm_link, enrol, given
from tests.test_notification_address import S, mail_env, outbox_rows, signed_in
from tests.test_requests import asked
from tests.test_runners import paired
from tests.test_two_factor import KEY, Clock
from tests.test_two_factor import moment as moment  # noqa: F401  (the clock fixture)

D = "/me/deletion"
LINK = re.compile(r"https://hub\.example/mail/account-deletion/(\S+)")


def admin_first(migrated: Engine, moment: Clock) -> str:
    """The instance admin is the earliest account (`admin.instance_admin_id`)."""
    admin = factory.human(migrated, "admin")
    moment.move(seconds=1)
    return admin


def person(
    make_client: ClientFactory, migrated: Engine, moment: Clock, handle: str = "pat"
) -> flow.Human:
    """Signed in by password just now, with a verified address and mail configured."""
    human = signed_in(make_client, migrated, handle, mail=mail_env().mail, secret_key=KEY)
    human.handle = handle
    assert human.patch(S, {"email": {"address": f"{handle}@example.org"}}).status_code == 200
    confirm_link(human, migrated)
    return human


def ask_deletion(human: flow.Human, confirm: str | None = None) -> Any:
    return human.post(D, {"confirm": confirm if confirm is not None else human.handle})


def requested(human: flow.Human, migrated: Engine) -> str:
    """Request the deletion; the token of the mailed link."""
    answer = ask_deletion(human)
    assert answer.status_code == 202, answer.text
    return token_of(migrated)


def token_of(migrated: Engine) -> str:
    mail = outbox_rows(migrated)[-1]
    found = LINK.search(mail.body)
    assert found, mail.body
    return found.group(1)


def page(human: flow.Human, token: str) -> Any:
    return human.client.get(f"/mail/account-deletion/{token}")


def press(human: flow.Human, token: str) -> Any:
    return human.client.post(f"/mail/account-deletion/{token}")


def deleted_at(migrated: Engine, human_id: str) -> Any:
    with migrated.connect() as conn:
        return conn.execute(select(t.human.c.deleted_at).where(t.human.c.id == human_id)).scalar()


def reason(response: Any) -> Any:
    return response.json()["error"]["details"].get("reason")


def code(response: Any) -> Any:
    return response.json()["error"]["code"]


# --- the request ---------------------------------------------------------------------------------


def test_the_request_needs_the_proof_and_the_step_up(
    make_client: ClientFactory, migrated: Engine, moment: Clock
) -> None:
    admin_first(migrated, moment)
    pat = person(make_client, migrated, moment)
    secret = enrol(pat, moment)
    moment.move(minutes=11)  # the password of the sign-in is too old now (§2.8.1)
    refused = ask_deletion(pat)
    assert (refused.status_code, reason(refused)) == (403, "reauthentication_required")
    assert pat.post("/auth/reauthenticate", {"password": factory.PASSWORD}).status_code == 200
    refused = ask_deletion(pat)
    assert (refused.status_code, reason(refused)) == (403, "step_up_required")
    mails = len(outbox_rows(migrated))
    given(pat, secret, moment)
    answer = ask_deletion(pat)
    assert answer.status_code == 202, answer.text
    assert len(outbox_rows(migrated)) == mails + 1


def test_confirm_is_the_callers_own_handle(
    make_client: ClientFactory, migrated: Engine, moment: Clock
) -> None:
    admin_first(migrated, moment)
    pat = person(make_client, migrated, moment)
    wrong = ask_deletion(pat, "admin")
    assert wrong.status_code == 400
    assert wrong.json()["error"]["details"]["fields"] == {"confirm": "mismatch"}
    assert pat.get("/me").json()["deletion"] is None


def test_an_agent_is_refused(make_client: ClientFactory, migrated: Engine, moment: Clock) -> None:
    admin_first(migrated, moment)
    owner = flow.human(make_client, migrated)
    flow.project(owner)
    agent = flow.agent(make_client, owner)
    for answer in (
        agent.post(D, {"confirm": "x"}),
        agent.client.delete("/api/v1" + D, headers=agent.auth),
    ):
        assert (answer.status_code, reason(answer)) == (403, "humans_only")


def test_the_request_is_mailed_and_shown_while_pending(
    make_client: ClientFactory, migrated: Engine, moment: Clock
) -> None:
    admin_first(migrated, moment)
    pat = person(make_client, migrated, moment)
    answer = ask_deletion(pat)
    assert answer.status_code == 202, answer.text
    deletion = answer.json()["deletion"]
    assert deletion == {
        "requested_at": clock.rfc3339(moment.at),
        "expires_at": clock.rfc3339(moment.at + timedelta(hours=24)),
    }
    assert pat.get("/me").json()["deletion"] == deletion
    mail = outbox_rows(migrated)[-1]
    assert (mail.kind, mail.recipient) == ("security", "pat@example.org")
    # The export link is the dashboard's account page, never the API route (§2.9).
    assert "https://hub.example/account\n" in mail.body and "/api/v1/me/export" not in mail.body
    token = token_of(migrated)
    shown = page(pat, token)
    assert shown.status_code == 200
    assert "Delete my account" in shown.text and "pat" in shown.text
    assert 'href="https://hub.example/account"' in shown.text
    assert shown.headers["Referrer-Policy"] == "no-referrer"
    assert deleted_at(migrated, pat.id) is None  # a GET changes nothing
    # Signing in still works until the link is pressed.
    assert pat.get("/me").status_code == 200
    # The request log masks the token like the other mail links (§18.6).
    path = f"/mail/account-deletion/{token}"
    assert any(p.match(path) for p in _TOKEN_PATHS)


def test_mail_and_a_verified_address_are_needed(
    make_client: ClientFactory, migrated: Engine, moment: Clock
) -> None:
    admin_first(migrated, moment)
    factory.human(migrated, "pat")
    without_mail = signed_in(make_client, migrated, "pat", secret_key=KEY)
    without_mail.handle = "pat"
    answer = ask_deletion(without_mail)
    assert (answer.status_code, code(answer)) == (409, "mail_not_configured")
    no_address = signed_in(make_client, migrated, "pat", mail=mail_env().mail, secret_key=KEY)
    no_address.handle = "pat"
    answer = ask_deletion(no_address)
    assert (answer.status_code, code(answer)) == (409, "address_unverified")


# --- refusals, at the request and again at the confirmation --------------------------------------


def test_a_namespace_owner_of_an_open_project_is_refused_both_times(
    make_client: ClientFactory, migrated: Engine, moment: Clock
) -> None:
    admin_first(migrated, moment)
    pat = person(make_client, migrated, moment)
    flow.project(pat, "own")
    refused = ask_deletion(pat)
    assert (refused.status_code, code(refused)) == (409, "namespace_owner")
    assert refused.json()["error"]["details"]["projects"] == ["pat/own"]
    with migrated.begin() as conn:
        conn.execute(update(t.project).values(state="archived"))
    token = requested(pat, migrated)
    flow.project(pat, "later")  # an open project again, after the request
    pressed = press(pat, token)
    assert pressed.status_code == 409 and "not archived" in pressed.text
    assert deleted_at(migrated, pat.id) is None
    assert pat.get("/me").status_code == 200  # nothing changed, the session included
    with migrated.begin() as conn:
        conn.execute(update(t.project).values(state="archived"))
    done = press(pat, token)  # the link kept working
    assert done.status_code == 200, done.text
    assert deleted_at(migrated, pat.id) is not None
    # The archived projects stay under their names; the last owner was allowed to go.
    with migrated.connect() as conn:
        rows = conn.execute(select(t.project.c.state, t.project.c.owner_id)).all()
        active = conn.execute(
            select(func.count()).select_from(t.membership).where(t.membership.c.active.is_(True))
        ).scalar_one()
    assert rows and all(r.state == "archived" and r.owner_id == pat.id for r in rows)
    assert active == 0


def test_the_last_instance_admin_is_refused_both_times(
    make_client: ClientFactory, migrated: Engine, moment: Clock
) -> None:
    admin = person(make_client, migrated, moment, "admin")  # the earliest account
    moment.move(seconds=1)
    refused = ask_deletion(admin)
    assert (refused.status_code, code(refused)) == (409, "last_instance_admin")
    pat = person(make_client, migrated, moment)
    token = requested(pat, migrated)
    with migrated.begin() as conn:  # pat becomes the earliest account, so the admin
        conn.execute(
            update(t.human)
            .where(t.human.c.id == admin.id)
            .values(created_at=moment.at.replace(year=2030))
        )
    pressed = press(pat, token)
    assert pressed.status_code == 409 and "last admin" in pressed.text
    assert deleted_at(migrated, pat.id) is None


# --- withdrawals and dead links ------------------------------------------------------------------


def dead(human: flow.Human, token: str, migrated: Engine) -> None:
    for answer in (page(human, token), press(human, token)):
        assert answer.status_code == 404 and "no longer works" in answer.text
    assert deleted_at(migrated, human.id) is None


def test_delete_withdraws_the_request(
    make_client: ClientFactory, migrated: Engine, moment: Clock
) -> None:
    admin_first(migrated, moment)
    pat = person(make_client, migrated, moment)
    token = requested(pat, migrated)
    withdrawn = pat.delete(D)
    assert (withdrawn.status_code, withdrawn.json()) == (200, {"deletion": None})
    assert pat.get("/me").json()["deletion"] is None
    dead(pat, token, migrated)
    assert pat.delete(D).json() == {"deletion": None}  # nothing pending answers the same


def test_a_newer_request_replaces_the_older(
    make_client: ClientFactory, migrated: Engine, moment: Clock
) -> None:
    admin_first(migrated, moment)
    pat = person(make_client, migrated, moment)
    first = requested(pat, migrated)
    second = requested(pat, migrated)
    assert first != second
    dead(pat, first, migrated)
    assert page(pat, second).status_code == 200
    with migrated.connect() as conn:
        rows = conn.execute(select(t.account_deletion)).all()
    # Both requests carry the same frozen clock value, so no column orders them.
    states = sorted(((r.live is True, r.withdrawn_by) for r in rows), key=lambda s: s[0])
    assert states == [(False, "replaced"), (True, None)]


def test_a_password_change_withdraws_the_request(
    make_client: ClientFactory, migrated: Engine, moment: Clock
) -> None:
    admin_first(migrated, moment)
    pat = person(make_client, migrated, moment)
    token = requested(pat, migrated)
    changed = pat.post(
        "/auth/password", {"current": factory.PASSWORD, "new": "another long secret"}
    )
    assert changed.status_code == 200, changed.text
    assert pat.get("/me").json()["deletion"] is None
    dead(pat, token, migrated)


@pytest.mark.parametrize("wanted", ["new@example.org", None])
def test_changing_or_removing_the_verified_address_withdraws_the_request(
    make_client: ClientFactory, migrated: Engine, moment: Clock, wanted: str | None
) -> None:
    admin_first(migrated, moment)
    pat = person(make_client, migrated, moment)
    token = requested(pat, migrated)
    changed = pat.patch(S, {"email": {"address": wanted}, "current_password": factory.PASSWORD})
    assert changed.status_code == 200, changed.text
    assert pat.get("/me").json()["deletion"] is None
    dead(pat, token, migrated)


def test_an_expired_or_forged_link_deletes_nothing(
    make_client: ClientFactory, migrated: Engine, moment: Clock
) -> None:
    admin_first(migrated, moment)
    pat = person(make_client, migrated, moment)
    token = requested(pat, migrated)
    dead(pat, token[:-2] + ("AA" if not token.endswith("AA") else "BB"), migrated)
    moment.move(hours=24, seconds=1)
    dead(pat, token, migrated)
    assert pat.get("/me").json()["deletion"] is None


# --- the deletion --------------------------------------------------------------------------------


def world(make_client: ClientFactory, migrated: Engine, moment: Clock) -> dict[str, Any]:
    """An admin, a project owner with `maintainer/maity`, and pat: an admin member of it
    with an agent, a runner, an open invitation, an open join, a request pat asked and a
    decision pat holds."""
    admin_first(migrated, moment)
    owner = flow.human(make_client, migrated)
    flow.project(owner)
    with migrated.connect() as conn:
        project_id = conn.execute(select(t.project.c.id)).scalar_one()
    pat = person(make_client, migrated, moment)
    pat_member = factory.membership(migrated, project_id, "admin", human_id=pat.id)
    agent = flow.agent(make_client, pat)
    runner = paired(make_client, pat)
    invitation = pat.post("/projects/maintainer/maity/invitations", {})
    assert invitation.status_code == 201, invitation.text
    open_join = flow.join(pat, "maity")
    question = asked(pat)
    held = asked(owner, to="trust:admin")
    claimed = pat.post(f"/projects/maintainer/maity/requests/{held['id']}/claim")
    assert claimed.status_code == 200, claimed.text
    return {
        "owner": owner,
        "pat": pat,
        "pat_member": pat_member,
        "agent": agent,
        "runner": runner,
        "invitation": invitation.json()["id"],
        "join": open_join,
        "question": question["id"],
        "held": held["id"],
        "project_id": project_id,
    }


def test_the_deletion_does_what_the_contract_lists(
    make_client: ClientFactory, migrated: Engine, moment: Clock
) -> None:
    w = world(make_client, migrated, moment)
    pat, owner, agent = w["pat"], w["owner"], w["agent"]
    with migrated.begin() as conn:  # a mail still waiting for the account
        conn.execute(
            insert(t.mail_outbox).values(
                kind="notification", human_id=pat.id, recipient="pat@example.org",
                subject="x", body="waiting", headers={}, created_at=moment.at,
                not_before=moment.at, attempts=0, status="waiting",
            )  # fmt: skip
        )
    token = requested(pat, migrated)
    done = press(pat, token)
    assert done.status_code == 200, done.text
    assert "deleted" in done.text
    # Access ends at once: the old cookie, the password, the agent's credential.
    assert pat.get("/me").status_code == 401
    login = make_client().post(
        "/api/v1/auth/login", json={"handle": "pat", "password": factory.PASSWORD}
    )
    assert login.status_code == 401
    assert agent.get("/me").status_code == 401
    assert press(pat, token).status_code == 404  # used
    with migrated.connect() as conn:
        human = conn.execute(select(t.human).where(t.human.c.id == pat.id)).one()
        assert human.deleted_at is not None and human.display_name == "Deleted account"
        assert human.handle == "pat"  # kept, so it stays taken
        sessions = (
            conn.execute(
                select(t.human_session.c.ended_by).where(t.human_session.c.human_id == pat.id)
            )
            .scalars()
            .all()
        )
        assert sessions and set(sessions) == {"account_deleted"}
        for table in (t.notification_settings, t.account_record, t.preferences):
            assert not conn.execute(select(table).where(table.c.human_id == pat.id)).first()
        waiting = conn.execute(
            select(t.mail_outbox.c.status).where(t.mail_outbox.c.body == "waiting")
        ).first()
        assert waiting is None  # dropped, its text gone
        # Leaves projects as a removal does.
        membership = conn.execute(
            select(t.membership).where(t.membership.c.id == w["pat_member"])
        ).one()
        assert membership.active is None and membership.removed_at is not None
        removed = conn.execute(
            select(t.event).where(
                t.event.c.kind == "member_updated",
                t.event.c.subject_id == pat.id,
            )
        ).all()
        assert removed and removed[-1].payload["removed_at"] is not None
        assert removed[-1].actor_membership is None  # the hub's change
        # Its agent profile is deleted as §6.3 does, its credential revoked.
        profile = conn.execute(
            select(t.agent_profile).where(t.agent_profile.c.id == agent.id)
        ).one()
        assert profile.deleted_at is not None
        credential = conn.execute(
            select(t.credential).where(t.credential.c.id == agent.credential_id)
        ).one()
        assert credential.revoked_at is not None
        # Its runner removed, its credential revoked.
        runner = conn.execute(select(t.runner).where(t.runner.c.id == w["runner"].id)).one()
        assert runner.removed_at is not None
        assert (
            conn.execute(
                select(t.runner_credential.c.revoked_at).where(
                    t.runner_credential.c.id == w["runner"].credential_id
                )
            ).scalar()
            is not None
        )
        # The open invitation voided, the open join revoked.
        invitation = conn.execute(
            select(t.invitation).where(t.invitation.c.id == w["invitation"])
        ).one()
        assert invitation.voided_at is not None
        join = conn.execute(select(t.join_link).where(t.join_link.c.id == w["join"]["id"])).one()
        assert join.revoked_at is not None
        # The decision it held went back to the admins.
        held = conn.execute(select(t.request).where(t.request.c.id == w["held"])).one()
        assert (held.holder_member, held.holder_pool) == (None, True)
    # The request it asked stays, shown as asked by a deleted account.
    shown = owner.get(f"/projects/maintainer/maity/requests/{w['question']}")
    assert shown.status_code == 200, shown.text
    asker = shown.json()["asked_by"]
    assert asker["member_id"] == pat.id
    assert {k: asker[k] for k in ("display_name", "handle", "avatar_url", "deleted")} == {
        "display_name": "Deleted account",
        "handle": None,
        "avatar_url": None,
        "deleted": True,
    }
    assert owner.get(f"/projects/maintainer/maity/requests/{w['held']}").json()["holder"] == (
        "trust:admin"
    )
    # The removal's member view shows the account without the person.
    events = owner.get("/projects/maintainer/maity/events?after=0").json()
    items = events.get("events", events.get("items", []))
    removal = [e for e in items if e["kind"] == "member_updated" and e["payload"]["id"] == pat.id][
        -1
    ]
    assert removal["actor"] is None  # the hub's change
    m = removal["payload"]
    assert (m["handle"], m["display_name"], m["avatar_url"], m["deleted"]) == (
        None,
        "Deleted account",
        None,
        True,
    )
    assert m["removed_at"] is not None
    # The handle stays taken: no new account gets it.
    with pytest.raises(IntegrityError):
        factory.human(migrated, "pat")
    from maity_hub.registration_accounts import check_names

    with migrated.connect() as conn:
        assert check_names(conn, "pat", "Pat")["handle"] == "taken"
    # The operator learns a count, nothing else.
    admin = signed_in(make_client, migrated, "admin")
    stats = admin.get("/admin/statistics").json()
    assert stats["totals"]["humans_deleted"] == 1
    listed = admin.get("/admin/users").json()["items"]
    assert pat.id not in [u["id"] for u in listed]


def test_the_deletion_is_one_transaction(
    make_client: ClientFactory, migrated: Engine, moment: Clock, monkeypatch: pytest.MonkeyPatch
) -> None:
    w = world(make_client, migrated, moment)
    pat = w["pat"]
    token = requested(pat, migrated)
    with migrated.connect() as conn:
        events_before = conn.execute(select(func.count()).select_from(t.event)).scalar_one()

    def broken(*args: Any) -> None:
        raise RuntimeError("the disk is full")

    # The last step fails, after every removal has run on the connection.
    monkeypatch.setattr(account_deletion, "_remove_person", broken)
    assert press(pat, token).status_code == 500
    with migrated.connect() as conn:
        assert conn.execute(select(func.count()).select_from(t.event)).scalar_one() == events_before
        membership = conn.execute(
            select(t.membership.c.active).where(t.membership.c.id == w["pat_member"])
        ).scalar()
        assert membership is True
        assert (
            conn.execute(
                select(t.agent_profile.c.deleted_at).where(t.agent_profile.c.id == w["agent"].id)
            ).scalar()
            is None
        )
        assert (
            conn.execute(
                select(t.runner.c.removed_at).where(t.runner.c.id == w["runner"].id)
            ).scalar()
            is None
        )
        assert (
            conn.execute(
                select(t.invitation.c.voided_at).where(t.invitation.c.id == w["invitation"])
            ).scalar()
            is None
        )
        request = conn.execute(select(t.account_deletion)).one()
        assert (request.live, request.used_at) == (True, None)
    assert pat.get("/me").status_code == 200  # the session still works
    assert w["agent"].get("/me").status_code == 200
    monkeypatch.undo()
    assert press(pat, token).status_code == 200  # the link still works, and now deletes
    assert deleted_at(migrated, pat.id) is not None


# --- review of #561: old payloads, tombstoned profiles, mail rows, the late write -----------------


def persons_of(value: Any, human_id: str, found: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Every object in `value` that names `human_id` as a person."""
    if isinstance(value, dict):
        if value.get("member_id") == human_id or (
            value.get("id") == human_id and value.get("kind") == "human"
        ):
            found.append(value)
        for inner in value.values():
            persons_of(inner, human_id, found)
    elif isinstance(value, list):
        for inner in value:
            persons_of(inner, human_id, found)
    return found


def test_old_event_payloads_show_the_deleted_account(
    make_client: ClientFactory, migrated: Engine, moment: Clock
) -> None:
    admin_first(migrated, moment)
    owner = flow.human(make_client, migrated)
    flow.project(owner)
    pat = person(make_client, migrated, moment)
    invited = owner.post("/projects/maintainer/maity/invitations", {})
    token = invited.json()["url"].rsplit("/", 1)[1]
    assert pat.post(f"/invitations/{token}/accept").status_code == 201  # member_joined
    asked(pat)  # request_created, asked_by pat
    to_pat = asked(owner, to=pat.id)
    answered = pat.post(
        f"/projects/maintainer/maity/requests/{to_pat['id']}/answer", {"text": "Do it."}
    )
    assert answered.status_code == 200, answered.text
    before = owner.get("/projects/maintainer/maity/events?after=0").json()
    assert "Human pat" in str(before)  # what was stored then
    assert press(pat, requested(pat, migrated)).status_code == 200
    events = owner.get("/projects/maintainer/maity/events?after=0").json()
    assert "Human pat" not in str(events)
    items = events.get("events", events.get("items", []))
    kinds = {e["kind"] for e in items}
    assert {"member_joined", "request_created", "request_answered"} <= kinds
    # Objects that show the person (a name or a handle); an actor's bare id stays.
    shown = [p for p in persons_of(items, pat.id, []) if "display_name" in p or "handle" in p]
    assert shown and all(p.get("deleted") is True for p in shown), [
        p for p in shown if not p.get("deleted")
    ]
    for p in shown:
        if "display_name" in p:
            assert (p["display_name"], p["handle"], p["avatar_url"]) == (
                "Deleted account",
                None,
                None,
            )
    created = next(
        e
        for e in items
        if e["kind"] == "request_created" and e["payload"]["asked_by"]["member_id"] == pat.id
    )
    assert created["payload"]["title"] == "Which?"  # free text unchanged
    # The stored rows stay as they were written: only the reading is shaped.
    with migrated.connect() as conn:
        stored = conn.execute(select(t.event.c.payload)).scalars().all()
    assert "Human pat" in str(stored)


def test_tombstoned_profiles_lose_git_identity_and_soul(
    make_client: ClientFactory, migrated: Engine, moment: Clock
) -> None:
    admin_first(migrated, moment)
    pat = person(make_client, migrated, moment)
    created = pat.post(
        "/agents",
        {
            "handle": "early",
            "display_name": "Early",
            "git_identity": {"name": "Early", "email": "early@example.org"},
        },
    )
    assert created.status_code == 201, created.text
    agent_id = created.json()["id"]
    with migrated.begin() as conn:
        conn.execute(
            insert(t.soul).values(
                agent_id=agent_id, markdown="who I am", version=1, by_kind="human",
                by_id=pat.id, updated_at=moment.at,
            )  # fmt: skip
        )
        conn.execute(
            insert(t.soul_version).values(
                agent_id=agent_id, version=1, markdown="who I am", by_kind="human",
                by_id=pat.id, at=moment.at,
            )  # fmt: skip
        )
    gone = pat.client.delete(
        f"/api/v1/agents/{agent_id}?cascade=true", headers={"X-CSRF-Token": pat.csrf}
    )
    assert gone.status_code == 200
    assert press(pat, requested(pat, migrated)).status_code == 200
    with migrated.connect() as conn:
        profile = conn.execute(
            select(t.agent_profile).where(t.agent_profile.c.id == agent_id)
        ).one()
        assert (profile.git_name, profile.git_email) == (None, None)
        for table in (t.soul, t.soul_version):
            assert not conn.execute(select(table).where(table.c.agent_id == agent_id)).first()


def test_no_mail_row_keeps_the_address(
    make_client: ClientFactory, migrated: Engine, moment: Clock
) -> None:
    admin_first(migrated, moment)
    pat = person(make_client, migrated, moment)
    with migrated.begin() as conn:
        for status in ("waiting", "sent", "failed"):
            conn.execute(
                insert(t.mail_outbox).values(
                    kind="notification", human_id=pat.id, recipient="pat@example.org",
                    subject="[Maity] pat", body="Hello pat", headers={"X": "pat"},
                    created_at=moment.at, not_before=moment.at, attempts=0, status=status,
                )  # fmt: skip
            )
        # A mail to the address that names no account (an invitation's).
        conn.execute(
            insert(t.mail_outbox).values(
                kind="security", human_id=None, recipient=" Pat@Example.org",
                subject="Invited", body="pat@example.org", headers={}, created_at=moment.at,
                not_before=moment.at, attempts=0, status="sent",
            )  # fmt: skip
        )
    assert press(pat, requested(pat, migrated)).status_code == 200
    with migrated.connect() as conn:
        for table in (t.mail_outbox, t.mail_delivery, t.pending_registration, t.invitation):
            for row in conn.execute(select(table)).all():
                assert "pat@example.org" not in str(tuple(row)).lower(), (table.name, row)
        statuses = conn.execute(select(t.mail_outbox.c.status)).scalars().all()
    assert "sent" in statuses and "failed" in statuses  # the counters' metadata stays


def test_a_write_held_past_its_authentication_is_refused_after_the_deletion(
    make_client: ClientFactory, migrated: Engine, moment: Clock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The reviewer's race: POST /agents is authenticated, the account is deleted, then
    the write runs. It must not commit."""
    from maity_hub import events, idempotency
    from maity_hub.deps import settings_of

    admin_first(migrated, moment)
    pat = person(make_client, migrated, moment)
    token = requested(pat, migrated)
    original = idempotency.run

    def held(engine: Engine, request: Any, caller: Any, action: Any) -> Any:
        # Between the authentication and the write: the link is pressed now, as its own
        # request (no caller bound, as on the link's page).
        def press_link() -> None:
            with events.transaction(engine) as conn:
                assert account_deletion.confirm(conn, settings_of(request), token) == "deleted"

        contextvars.Context().run(press_link)
        return original(engine, request, caller, action)

    monkeypatch.setattr(idempotency, "run", held)
    late = pat.post(
        "/agents",
        {
            "handle": "late-agent",
            "display_name": "Late",
            "git_identity": {"name": "Late", "email": "late@example.org"},
        },
    )
    assert late.status_code == 401, late.text
    monkeypatch.undo()
    assert deleted_at(migrated, pat.id) is not None
    with migrated.connect() as conn:
        assert not conn.execute(
            select(t.agent_profile).where(t.agent_profile.c.handle == "late-agent")
        ).first()


def test_a_reopen_racing_the_confirmation_is_seen(
    make_client: ClientFactory, migrated: Engine, moment: Clock
) -> None:
    """A reopen of an archived project in the namespace holds the project's lock; the
    confirmation's re-check waits for it and then refuses (PostgreSQL, MariaDB)."""
    from tests.concurrency import finished, race, waiting

    admin_first(migrated, moment)
    pat = person(make_client, migrated, moment)
    flow.project(pat, "own")
    with migrated.begin() as conn:
        conn.execute(update(t.project).values(state="archived"))
        project_id = conn.execute(select(t.project.c.id)).scalar_one()
    token = requested(pat, migrated)
    hub = mail_env()
    with race(migrated) as r:
        reopen, deletion = r.first, r.second
        lock_project(reopen, project_id)
        reopen.execute(update(t.project).where(t.project.c.id == project_id).values(state="build"))
        step = r.run(deletion, lambda: account_deletion.confirm(deletion, hub, token))
        assert waiting(step)  # blocked on the project's lock
        reopen.commit()
        assert finished(step) == "namespace_owner"
        deletion.rollback()
    assert deleted_at(migrated, pat.id) is None


# --- re-review of #561: stored mentions on every read path, one lock order -----------------------


def deleted_mentions(value: Any, human_id: str) -> list[dict[str, Any]]:
    named = [p for p in persons_of(value, human_id, []) if "handle" in p]
    assert named, value
    return named


def test_stored_mentions_in_requests_and_cards_show_the_deleted_account(
    make_client: ClientFactory, migrated: Engine, moment: Clock
) -> None:
    admin_first(migrated, moment)
    owner = flow.human(make_client, migrated)
    flow.project(owner)
    pat = person(make_client, migrated, moment)
    with migrated.connect() as conn:
        project_id = conn.execute(select(t.project.c.id)).scalar_one()
    factory.membership(migrated, project_id, "member", human_id=pat.id)
    request = asked(owner, summary="What does @pat think?")
    card = owner.post("/projects/maintainer/maity/tasks", {"title": "A card", "body": "For @pat"})
    assert card.status_code == 201, card.text
    assert deleted_mentions(request["mentions"], pat.id)[0]["handle"] == "pat"
    assert press(pat, requested(pat, migrated)).status_code == 200
    base = "/projects/maintainer/maity"
    reads = {
        "request": owner.get(f"{base}/requests/{request['id']}").json(),
        "requests": owner.get(f"{base}/requests?status=all").json(),
        "card": owner.get(f"{base}/tasks/{card.json()['id']}").json(),
        "cards": owner.get(f"{base}/tasks").json(),
    }
    for name, body in reads.items():
        for mention in deleted_mentions(body, pat.id):
            assert (mention["handle"], mention["deleted"]) == (None, True), name
    # Free text is unchanged.
    assert reads["request"]["summary"] == "What does @pat think?"
    assert reads["card"]["body"] == "For @pat"


def test_the_account_lock_comes_before_any_other_lock_of_a_human_write(
    make_client: ClientFactory, migrated: Engine, moment: Clock
) -> None:
    """Every transaction of a human caller that locks anything takes `account_lock`
    first (`write_guard`), so it shares the deletion's order."""
    from sqlalchemy import event

    from maity_hub import write_guard

    admin_first(migrated, moment)
    pat = person(make_client, migrated, moment)
    flow.project(pat, "own")
    seen: list[list[str]] = []

    def begin(conn: Any) -> None:
        seen.append([])

    def statement(conn: Any, cursor: Any, text: str, *args: Any) -> None:
        if seen:
            seen[-1].append(text)

    event.listen(migrated, "begin", begin)
    event.listen(migrated, "before_cursor_execute", statement)
    try:
        assert pat.post("/agents", {"handle": "first", "display_name": "First"}).status_code == 201
        assert pat.patch("/projects/pat/own", {"name": "Renamed"}).status_code == 200
    finally:
        event.remove(migrated, "begin", begin)
        event.remove(migrated, "before_cursor_execute", statement)
    guarded = 0
    for statements in seen:
        statements = [s for s in statements if not s.upper().startswith("BEGIN")]
        first = next((i for i, s in enumerate(statements) if write_guard.locking(s)), None)
        if first is None or "human_session" in statements[first]:
            continue  # read-only, or the authentication's own (checked by `_cookie`)
        before = statements[:first]
        # SQLite renders no lock clause: the account lock's read is what comes first.
        assert any("FROM account_lock" in s for s in before), statements
        guarded += 1
    assert guarded >= 2  # the profile's and the project's transactions


def test_the_account_lock_is_taken_outside_any_savepoint(
    make_client: ClientFactory, migrated: Engine, moment: Clock
) -> None:
    """A transaction that opens a savepoint before its first lock takes `account_lock`
    before the SAVEPOINT, so a rolled-back savepoint cannot give the lock up."""
    from sqlalchemy import event, insert, update

    from maity_hub import write_guard
    from maity_hub.errors import ApiError

    admin_first(migrated, moment)
    pat = person(make_client, migrated, moment)
    seen: list[str] = []

    def statement(conn: Any, cursor: Any, text: str, *args: Any) -> None:
        seen.append(text)

    event.listen(migrated, "before_cursor_execute", statement)
    token = write_guard._HUMAN.set(pat.id)
    try:
        with migrated.begin() as conn:
            try:
                with conn.begin_nested():
                    conn.execute(insert(t.account_lock).values(human_id=pat.id))  # a duplicate
            except Exception:
                pass  # the savepoint rolls back, as a helper's caught IntegrityError does
            conn.execute(update(t.human).where(t.human.c.id == pat.id).values(display_name="Pat"))
    except ApiError:
        raise
    finally:
        write_guard._HUMAN.reset(token)
        event.remove(migrated, "before_cursor_execute", statement)
    savepoint = next(i for i, s in enumerate(seen) if s.upper().startswith("SAVEPOINT"))
    assert any("FROM account_lock" in s for s in seen[:savepoint]), seen


def test_a_profile_delete_racing_the_deletion_does_not_deadlock(
    make_client: ClientFactory, migrated: Engine, moment: Clock
) -> None:
    """The reviewer's interleaving: pat's `DELETE /agents/{id}` holds the profile lock,
    the confirmation starts; with one lock order the confirmation waits for the account
    lock, the profile deletion commits, then the account is deleted (PostgreSQL, MariaDB)."""
    from maity_hub import write_guard
    from maity_hub.routes.agents import delete_profile, owned
    from tests.concurrency import finished, race, waiting

    admin_first(migrated, moment)
    pat = person(make_client, migrated, moment)
    created = pat.post("/agents", {"handle": "doomed", "display_name": "Doomed"})
    agent_id = created.json()["id"]
    token = requested(pat, migrated)
    hub = mail_env()
    with race(migrated) as r:
        profile, deletion = r.first, r.second
        write_guard.hold(profile, pat.id)  # what the hook does before the first lock
        owned(profile, agent_id, pat.id, deleted=True, lock=True)
        step = r.run(deletion, lambda: account_deletion.confirm(deletion, hub, token))
        assert waiting(step)  # on the account lock, holding nothing the profile needs
        delete_profile(
            profile, agent_id, actor_in=lambda _p: account_deletion.HUB, by=pat.id,
            credential_id=None, via=None,
        )  # fmt: skip
        profile.commit()
        assert finished(step) == "deleted"
        deletion.commit()
    assert deleted_at(migrated, pat.id) is not None


def test_forge_links_and_sign_in_links_go_with_the_account(
    make_client: ClientFactory, migrated: Engine, moment: Clock
) -> None:
    """§2.9 "Ends access at once": the forge links with their pending state and token
    (§11.4) and the pending sign-in links (§2.6.3), with the day's wrong-code count, go."""
    admin_first(migrated, moment)
    pat = person(make_client, migrated, moment)
    now = clock.now()
    with migrated.begin() as conn:
        conn.execute(
            insert(t.email_sign_in).values(
                nonce_hash="a" * 64, pending_hash="b" * 64, human_id=pat.id, address_epoch=1,
                source="password", next_path="/", wrong_codes=0, created_at=now,
                expires_at=now + timedelta(minutes=15),
            )
        )  # fmt: skip
        conn.execute(
            insert(t.email_sign_in_day).values(human_id=pat.id, day="2026-10-29", wrong_codes=2)
        )
        conn.execute(
            insert(t.forge_link).values(
                id="fgl-pat", human_id=pat.id, forge="github", installation_id=4711,
                account_id=1, account_login="pat", account_type="User",
                repository_selection="all", status="active", linked_at=now, checked_at=now,
            )
        )  # fmt: skip
        conn.execute(
            insert(t.forge_link_state).values(
                state_hash="c" * 64, human_id=pat.id, session_hash="d" * 64,
                expires_at=now + timedelta(minutes=10),
            )
        )  # fmt: skip
        conn.execute(
            insert(t.forge_token).values(
                human_id=pat.id, forge="github", login="pat", token_sealed=b"sealed",
                status="active", set_at=now, checked_at=now,
            )
        )  # fmt: skip
    token = requested(pat, migrated)
    assert press(pat, token).status_code == 200
    with migrated.connect() as conn:
        for table in (
            t.email_sign_in,
            t.email_sign_in_day,
            t.forge_link,
            t.forge_link_state,
            t.forge_token,
        ):
            left = conn.execute(select(table).where(table.c.human_id == pat.id)).first()
            assert left is None, table.name
