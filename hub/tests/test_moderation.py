"""docs/api.md §16.8, the actions: what resolving a report changes, as actor
`{kind: "moderation", report_id}`, the holds ordinary writes cannot undo, and a
suspension that ends every way in."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import Engine, select, update

from maity_hub import moderation
from maity_hub import tables as t
from maity_hub.errors import ApiError
from tests import factory, flow
from tests import test_runners as runners
from tests.conftest import ClientFactory
from tests.test_reports import PROJECT, a_card, message, report
from tests.test_reports import team as team  # noqa: F401  (the fixture)
from tests.test_two_factor import moment as moment  # noqa: F401  (the clock fixture)


def resolve(team: dict[str, Any], report_id: str, action: str, note: str | None = None) -> Any:
    body: dict[str, Any] = {"action": action}
    if note is not None:
        body["note"] = note
    return team["owner"].post(f"/admin/reports/{report_id}/resolve", body)


def events(who: Any) -> list[dict[str, Any]]:
    found = who.get(f"/projects/{PROJECT}/events?after=0").json()
    items: list[dict[str, Any]] = found.get("events", found.get("items", []))
    return items


def held(response: Any) -> None:
    assert response.status_code == 403, response.text
    assert response.json()["error"]["details"]["reason"] == "moderation_hold"


def test_hide_takes_a_project_members_only_until_dismissed(
    team: dict[str, Any], migrated: Engine
) -> None:
    owner = team["owner"]
    owner.patch(f"/projects/{PROJECT}", {"policy": {"swarm_public": "on"}, "reason": "show"})
    made = report(team["pat"], {"type": "project", "id": PROJECT}).json()
    assert resolve(team, made["id"], "hide", "spam page").status_code == 200
    project = owner.get(f"/projects/{PROJECT}").json()
    assert (project["policy"]["badge"], project["policy"]["swarm_public"]) == ("off", "off")
    assert project["moderation"]["action"] == "hide"
    assert project["moderation"]["report_id"] == made["id"]
    [changed] = [e for e in events(owner) if e["kind"] == "policy_changed"][-1:]
    assert changed["actor"] == {"kind": "moderation", "report_id": made["id"]}
    assert changed["payload"]["reason"] == "spam page"
    held(owner.patch(f"/projects/{PROJECT}", {"policy": {"badge": "members"}}))
    assert resolve(team, made["id"], "dismiss").status_code == 200
    assert "moderation" not in owner.get(f"/projects/{PROJECT}").json()
    again = owner.patch(f"/projects/{PROJECT}", {"policy": {"badge": "members"}})
    assert again.status_code == 200, again.text  # lifting restored nothing by itself


def test_remove_archives_a_project_that_stays_archived(
    team: dict[str, Any], migrated: Engine
) -> None:
    owner = team["owner"]
    badge = owner.patch(f"/projects/{PROJECT}", {"policy": {"badge": "members"}})
    assert badge.status_code == 200, badge.text
    made = report(team["pat"], {"type": "project", "id": PROJECT}).json()
    assert resolve(team, made["id"], "remove", "scam").status_code == 200
    assert owner.get(f"/projects/{PROJECT}").json()["state"] == "archived"
    held(owner.patch(f"/projects/{PROJECT}", {"state": "build", "reason": "back"}))
    # A surface left as it was blocks no other policy change (the badge was on).
    other = owner.patch(f"/projects/{PROJECT}", {"policy": {"subtasks": "direct"}, "reason": "x"})
    assert other.status_code == 200, other.text


def test_remove_cancels_a_card_and_redacts_a_message(
    team: dict[str, Any], migrated: Engine
) -> None:
    owner, pat = team["owner"], team["pat"]
    card = a_card(team, migrated, title="Free tokens")
    on_card = report(pat, {"type": "card", "id": card, "project": PROJECT}).json()
    assert resolve(team, on_card["id"], "remove").status_code == 200
    shown = owner.get(f"/projects/{PROJECT}/tasks/{card}").json()
    assert shown["status"] == "cancelled" and shown["moderation"]["action"] == "remove"
    held(owner.patch(f"/projects/{PROJECT}/tasks/{card}", {"status": "open"}))

    seq = message(owner, body="buy tokens here")
    on_message = report(pat, {"type": "message", "id": str(seq), "project": PROJECT}).json()
    assert resolve(team, on_message["id"], "remove", "spam").status_code == 200
    with migrated.connect() as conn:
        row = conn.execute(select(t.event).where(t.event.c.seq == seq)).one()
    assert row.redacted and row.payload["reason"] == "spam" and row.payload["by"] is None
    [notice] = [e for e in events(owner) if e["kind"] == "event_redacted"]
    assert notice["actor"] == {"kind": "moderation", "report_id": on_message["id"]}
    [shown] = [e for e in events(owner) if e["seq"] == seq]
    assert shown["moderation"]["report_id"] == on_message["id"]


def test_remove_resets_an_agent_profile_and_holds_it(
    team: dict[str, Any], make_client: ClientFactory, migrated: Engine
) -> None:
    owner = team["owner"]
    agent = flow.agent(make_client, owner)
    renamed = owner.patch(f"/agents/{agent.id}", {"display_name": "Totally Legit Bank"})
    assert renamed.status_code == 200, renamed.text
    made = report(team["pat"], {"type": "profile", "id": agent.id}, "impersonation").json()
    assert resolve(team, made["id"], "remove").status_code == 200
    profile = owner.get(f"/agents/{agent.id}").json()
    assert profile["display_name"] == profile["handle"]
    assert profile["moderation"]["action"] == "remove"
    held(owner.patch(f"/agents/{agent.id}", {"display_name": "Totally Legit Bank"}))


def test_the_affected_account_is_told_never_who_reported(
    team: dict[str, Any], migrated: Engine
) -> None:
    pat = team["pat"]
    seq = message(pat, body="spam from pat")
    made = report(team["owner"], {"type": "message", "id": str(seq), "project": PROJECT}).json()
    assert resolve(team, made["id"], "hide", "not here").status_code == 200
    [item] = [
        i
        for i in pat.get("/me/notifications").json()["items"]
        if i["target"] == {"type": "moderation", "id": made["id"]}
    ]
    assert item["kind"] == "inbox" and item["title"] == "Moderation: hide — message: not here"
    assert team["owner"].handle not in item["title"]


def test_suspend_ends_every_way_in_until_the_operator_lifts_it(
    team: dict[str, Any], make_client: ClientFactory, migrated: Engine
) -> None:
    owner, pat = team["owner"], team["pat"]
    flow.project(pat, "pats")
    agent = flow.agent(make_client, pat, "pat/pats")
    seq = message(pat, body="spam from pat")
    made = report(owner, {"type": "message", "id": str(seq), "project": PROJECT}).json()
    assert resolve(team, made["id"], "suspend", "spam run").status_code == 200

    assert pat.get("/me").status_code == 401  # the session ended
    assert agent.get("/me").status_code == 401  # and the agent's credential
    with migrated.connect() as conn:
        reasons = conn.execute(
            select(t.credential.c.revoked_reason)
            .join(t.membership, t.membership.c.id == t.credential.c.membership_id)
            .where(t.membership.c.agent_id == agent.id)
        ).scalars()
        assert set(reasons) == {"suspended"}
    login = make_client().post(
        "/api/v1/auth/login", json={"handle": "pat", "password": factory.PASSWORD}
    )
    wrong = make_client().post(
        "/api/v1/auth/login", json={"handle": "pat", "password": "not the password"}
    )
    assert (login.status_code, login.json()) == (wrong.status_code, wrong.json())

    # Its memberships act as paused (§5.3).
    members = owner.get(f"/projects/{PROJECT}/members").json()["items"]
    shown = next(m for m in members if m["handle"] == "pat")
    assert shown["presence"] == "paused"
    assert shown["paused"]["reason"] == "account suspended"

    # A dismiss lifts holds, never a suspension: that is the operator's.
    assert resolve(team, made["id"], "dismiss").status_code == 200
    assert (
        make_client()
        .post("/api/v1/auth/login", json={"handle": "pat", "password": factory.PASSWORD})
        .status_code
        == 401
    )
    with migrated.begin() as conn:
        assert moderation.unsuspend(conn, pat.id)
    back = make_client().post(
        "/api/v1/auth/login", json={"handle": "pat", "password": factory.PASSWORD}
    )
    assert back.status_code == 200, back.text


def test_suspend_needs_an_account(team: dict[str, Any], migrated: Engine) -> None:
    seq = message(team["pat"], body="spam from pat")
    made = report(team["owner"], {"type": "message", "id": str(seq), "project": PROJECT}).json()
    with migrated.begin() as conn:
        conn.execute(
            update(t.human)
            .where(t.human.c.id == team["pat"].id)
            .values(deleted_at=t.human.c.created_at)
        )
    refused = resolve(team, made["id"], "suspend")
    assert refused.status_code == 400
    assert refused.json()["error"]["details"]["reason"] == "no_account"


def test_a_suspended_account_gets_no_new_credential(
    team: dict[str, Any], make_client: ClientFactory, migrated: Engine
) -> None:
    """A join and a runner pairing made before the suspension are exchanged after it."""
    owner = team["owner"]
    created = flow.join(owner, "maity")
    enrolled = runners.enroll(owner)
    with migrated.begin() as conn:
        moderation.suspend(conn, owner.id, "rpt-000000000000")
    for refused in (
        flow.exchange(make_client(), created),
        runners.exchange(make_client(), enrolled),
    ):
        assert refused.status_code == 403, refused.text
        assert refused.json()["error"]["code"] == "account_suspended"


def test_an_issue_waits_for_a_suspension_in_progress(
    team: dict[str, Any], migrated: Engine
) -> None:
    """The order of §2.9: the suspension holds the account lock exclusively until it
    commits, an issue takes it shared before it reads the column, so it waits and then
    refuses; reading the column alone would see it unset and issue (PostgreSQL, MariaDB)."""
    from tests.concurrency import finished, race, waiting

    owner = team["owner"]
    with race(migrated) as r:
        suspension, issue = r.first, r.second
        moderation.suspend(suspension, owner.id, "rpt-000000000000")
        step = r.run(issue, lambda: moderation.refuse_suspended(issue, owner.id))
        assert waiting(step)  # on the account lock
        suspension.commit()
        with pytest.raises(ApiError) as refused:
            finished(step)
        assert refused.value.code == "account_suspended"


def test_an_agent_on_a_public_swarm_page_can_be_reported_by_its_name(
    team: dict[str, Any], make_client: ClientFactory, migrated: Engine
) -> None:
    """Strangers see it there (§6.22), so they report it there (§16.8)."""
    owner, stranger = team["owner"], team["stranger"]
    agent = flow.agent(make_client, owner)
    name = f"maintainer/{owner.get(f'/agents/{agent.id}').json()['handle']}"
    assert report(stranger, {"type": "profile", "id": name}).status_code == 404
    on = owner.patch(f"/projects/{PROJECT}", {"policy": {"swarm_public": "on"}, "reason": "show"})
    assert on.status_code == 200, on.text
    made = report(stranger, {"type": "profile", "id": name})
    assert made.status_code == 201, made.text
    shown = owner.get(f"/admin/reports/{made.json()['id']}").json()
    assert shown["target"] == {"type": "profile", "id": agent.id}


def test_a_project_report_follows_a_rename(team: dict[str, Any], migrated: Engine) -> None:
    made = report(team["pat"], {"type": "project", "id": PROJECT}).json()
    with migrated.connect() as conn:
        stored = conn.execute(select(t.abuse_report.c.target_id)).scalar_one()
    assert stored == team["project_id"]
    shown = team["owner"].get(f"/admin/reports/{made['id']}").json()
    assert shown["target"] == {"type": "project", "id": PROJECT}


def test_a_held_human_profile_shows_its_hold(team: dict[str, Any], migrated: Engine) -> None:
    pat = team["pat"]
    made = report(team["owner"], {"type": "profile", "id": pat.id}, "impersonation").json()
    assert resolve(team, made["id"], "hide").status_code == 200
    assert pat.get("/me").json()["member"]["moderation"]["action"] == "hide"
    members = team["owner"].get(f"/projects/{PROJECT}/members").json()["items"]
    shown = next(m for m in members if m["handle"] == "pat")
    assert shown["moderation"]["report_id"] == made["id"]
