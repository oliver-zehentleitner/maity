"""Deleting your own account (docs/api.md §2.9): the request with its proof and step-up,
the refusals, the mailed link and its page, every withdrawal, and what the deletion does,
in one transaction."""

from __future__ import annotations

import re
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import Engine, func, insert, select, update
from sqlalchemy.exc import IntegrityError

from maity_hub import account_deletion, clock
from maity_hub import tables as t
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
    assert "https://hub.example/#/account\n" in mail.body and "/api/v1/me/export" not in mail.body
    token = token_of(migrated)
    shown = page(pat, token)
    assert shown.status_code == 200
    assert "Delete my account" in shown.text and "pat" in shown.text
    assert 'href="https://hub.example/#/account"' in shown.text
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
        rows = conn.execute(
            select(t.account_deletion).order_by(t.account_deletion.c.requested_at)
        ).all()
    assert [(r.live, r.withdrawn_by) for r in rows] == [(None, "replaced"), (True, None)]


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
