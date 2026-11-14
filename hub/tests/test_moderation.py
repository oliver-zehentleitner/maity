"""docs/api.md §16.8, the actions: what resolving a report changes, as actor
`{kind: "moderation", report_id}`, the holds ordinary writes cannot undo, and a
suspension that ends every way in."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

import pytest
from sqlalchemy import Engine, event, select, update

from maity_hub import events as event_log
from maity_hub import moderation
from maity_hub import tables as t
from maity_hub.errors import ApiError
from maity_hub.write_guard import locking
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
    shown = owner.patch(f"/projects/{PROJECT}", {"policy": {"badge": "members"}, "reason": "show"})
    assert shown.status_code == 200, shown.text
    made = report(team["pat"], {"type": "project", "id": PROJECT}).json()
    assert resolve(team, made["id"], "hide", "spam page").status_code == 200
    project = owner.get(f"/projects/{PROJECT}").json()
    assert project["policy"]["badge"] == "off"
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


def test_remove_resets_an_uploaded_picture_as_the_moderation(
    team: dict[str, Any], make_client: ClientFactory, migrated: Engine
) -> None:
    """A reset that changes the picture emits `avatar_changed` with the moderation as actor;
    it answered 500 before (`announce` read the actor as a caller)."""
    from tests.test_avatars import image, put_agent

    owner = team["owner"]
    agent = flow.agent(make_client, owner)
    assert put_agent(agent, image()).status_code == 200
    made = report(team["pat"], {"type": "profile", "id": agent.id}, "impersonation").json()
    assert resolve(team, made["id"], "remove").status_code == 200
    assert owner.get(f"/agents/{agent.id}").json()["avatar_source"] == "generated"
    [changed] = [e for e in events(owner) if e["kind"] == "avatar_changed"][-1:]
    assert changed["actor"] == {"kind": "moderation", "report_id": made["id"]}


def test_remove_drops_an_agents_motif_and_the_hold_refuses_a_new_one(
    team: dict[str, Any], make_client: ClientFactory, migrated: Engine
) -> None:
    """§16.8: a reset drops an agent's upload and motif, so its generated picture shows, and
    while the hold stands neither its owner nor the agent chooses a motif again; clearing
    one stays allowed."""
    from maity_hub import avatars, motifs

    owner = team["owner"]
    agent = flow.agent(make_client, owner)
    name = motifs.current().motifs[0].name
    chose = owner.patch(f"/agents/{agent.id}", {"avatar_motif": name})
    assert chose.status_code == 200 and chose.json()["avatar_source"] == "motif", chose.text
    made = report(team["pat"], {"type": "profile", "id": agent.id}, "impersonation").json()
    assert resolve(team, made["id"], "remove").status_code == 200
    profile = owner.get(f"/agents/{agent.id}").json()
    assert (profile["avatar_source"], profile["avatar_motif"]) == ("generated", None)
    [changed] = [e for e in events(owner) if e["kind"] == "avatar_changed"][-1:]
    assert changed["actor"] == {"kind": "moderation", "report_id": made["id"]}
    held(owner.patch(f"/agents/{agent.id}", {"avatar_motif": name}))
    held(agent.patch("/me", {"avatar_motif": name}))
    avatars.CHANGES.reset()
    assert owner.patch(f"/agents/{agent.id}", {"avatar_motif": None}).status_code == 200
    assert resolve(team, made["id"], "dismiss").status_code == 200
    again = owner.patch(f"/agents/{agent.id}", {"avatar_motif": name})
    assert again.status_code == 200, again.text  # the hold lifted, the choice is the owner's


@contextmanager
def reset_waiting(migrated: Engine, owner_id: str, report_id: str) -> Iterator[Any]:
    """A `remove` of `owner_id`'s profile in progress, as `moderation.apply` leaves it after
    `_reset_profile` and its own insert of the hold, in the same transaction: the owner's
    row lock held, the hold written, nothing committed yet. An agent's or a human's row.
    Yields a function that runs a change in the other transaction and then commits the
    reset (PostgreSQL, MariaDB)."""
    from maity_hub import avatars, clock
    from tests.concurrency import finished, race, waiting

    with race(migrated) as r:
        reset = r.first
        avatars.lock_owner(reset, owner_id)
        reset.execute(
            t.moderation_hold.insert().values(
                report_id=report_id,
                target_type="profile",
                target_id=owner_id,
                action="remove",
                at=clock.now(),
            )
        )

        def change(send: Callable[[], Any]) -> Any:
            step = r.run(r.second, send)
            assert waiting(step)  # on the picture's lock, which the reset holds
            reset.commit()
            return finished(step)

        yield change


def test_a_motif_chosen_while_a_reset_holds_the_lock_is_refused_by_its_hold(
    team: dict[str, Any], make_client: ClientFactory, migrated: Engine
) -> None:
    """§16.8: the choice reads the hold after the picture's lock, so a choice that waited for
    a reset sees the hold it wrote; read before the lock, it found none and set the motif."""
    from maity_hub import motifs

    owner = team["owner"]
    agent = flow.agent(make_client, owner)
    name = motifs.current().motifs[0].name
    made = report(team["pat"], {"type": "profile", "id": agent.id}, "impersonation").json()
    with reset_waiting(migrated, agent.id, made["id"]) as change:
        held(change(lambda: owner.patch(f"/agents/{agent.id}", {"avatar_motif": name})))
    profile = owner.get(f"/agents/{agent.id}").json()
    assert (profile["avatar_source"], profile["avatar_motif"]) == ("generated", None)


def test_an_upload_while_a_reset_holds_the_lock_is_refused_by_its_hold(
    team: dict[str, Any], make_client: ClientFactory, migrated: Engine
) -> None:
    """§16.8, the upload's path: the same order, the lock before the hold is read."""
    from tests.test_avatars import image, put_agent

    owner = team["owner"]
    agent = flow.agent(make_client, owner)
    made = report(team["pat"], {"type": "profile", "id": agent.id}, "impersonation").json()
    with reset_waiting(migrated, agent.id, made["id"]) as change:
        held(change(lambda: put_agent(agent, image())))
    assert owner.get(f"/agents/{agent.id}").json()["avatar_source"] == "generated"


def test_a_display_name_set_while_a_reset_holds_the_lock_is_refused_by_its_hold(
    team: dict[str, Any], make_client: ClientFactory, migrated: Engine
) -> None:
    """§16.8: the display name reads the hold after the profile's row lock, so a change
    that waited for a reset sees the hold it wrote and the name stays the handle."""
    owner = team["owner"]
    agent = flow.agent(make_client, owner)
    profile = owner.get(f"/agents/{agent.id}").json()
    # A reset leaves the name as the handle; the change under test tries to put another on it.
    named = owner.patch(f"/agents/{agent.id}", {"display_name": profile["handle"]})
    assert named.status_code == 200, named.text
    made = report(team["pat"], {"type": "profile", "id": agent.id}, "impersonation").json()

    def send() -> Any:
        return owner.patch(f"/agents/{agent.id}", {"display_name": "Totally Legit Bank"})

    with reset_waiting(migrated, agent.id, made["id"]) as change:
        held(change(send))
    again = owner.get(f"/agents/{agent.id}").json()
    assert again["display_name"] == again["handle"]


def test_a_name_committed_before_the_reset_locks_is_reset_to_the_handle(
    team: dict[str, Any],
    make_client: ClientFactory,
    migrated: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§16.8: the reset reads the name after the owner's lock, so a name committed
    between the reset's start and that lock is reset to the handle too."""
    from maity_hub import avatars, forge, reports
    from tests.concurrency import race

    owner = team["owner"]
    agent = flow.agent(make_client, owner)
    profile = owner.get(f"/agents/{agent.id}").json()
    # The read before the lock must already see the handle, or it would write the handle
    # from that read and the name committed in between would not survive.
    named = owner.patch(f"/agents/{agent.id}", {"display_name": profile["handle"]})
    assert named.status_code == 200, named.text
    made = report(team["pat"], {"type": "profile", "id": agent.id}, "impersonation").json()
    real_lock = avatars.lock_owner
    state = {"done": False}

    def lock(conn: Any, owner_id: str) -> None:
        if owner_id == agent.id and not state["done"]:
            state["done"] = True
            sent = owner.patch(f"/agents/{agent.id}", {"display_name": "Totally Legit Bank"})
            assert sent.status_code == 200, sent.text
        real_lock(conn, owner_id)

    monkeypatch.setattr(avatars, "lock_owner", lock)
    with race(migrated) as r:
        reports.resolve(r.first, owner.id, made["id"], "remove", None, forge.Forge())
        r.first.commit()
    again = owner.get(f"/agents/{agent.id}").json()
    assert again["display_name"] == again["handle"]


def test_a_public_profile_while_a_reset_holds_the_lock_is_refused_by_its_hold(
    team: dict[str, Any], migrated: Engine
) -> None:
    """§16.8: turning a person's page on reads the hold after their row lock, so a change
    that waited for a reset of that profile sees the hold and the page stays off."""
    owner = team["owner"]
    off = owner.patch("/me", {"public_profile": False})
    assert off.status_code == 200, off.text
    made = report(team["pat"], {"type": "profile", "id": owner.id}, "spam").json()
    with reset_waiting(migrated, owner.id, made["id"]) as change:
        held(change(lambda: owner.patch("/me", {"public_profile": True})))
    assert owner.get("/me").json()["member"]["public_profile"] is False


def test_a_public_profile_while_a_hide_holds_the_lock_is_refused_by_its_hold(
    team: dict[str, Any], migrated: Engine
) -> None:
    """§16.8: `hide` on a profile locks the owner's row before it writes the hold, so
    turning the page on waits for that hide and then reads the hold."""
    from maity_hub import forge, reports
    from tests.concurrency import finished, race, waiting

    owner = team["owner"]
    off = owner.patch("/me", {"public_profile": False})
    assert off.status_code == 200, off.text
    made = report(team["pat"], {"type": "profile", "id": owner.id}, "impersonation").json()
    with race(migrated) as r:
        reports.resolve(r.first, owner.id, made["id"], "hide", None, forge.Forge())
        step = r.run(r.second, lambda: owner.patch("/me", {"public_profile": True}))
        assert waiting(step)  # on the owner's row, which the hide holds
        r.first.commit()
        held(finished(step))
    assert owner.get("/me").json()["member"]["public_profile"] is False


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
        # Said as a revocation by hand says it, to the agent and the project's owners.
        said = conn.execute(
            select(t.event.c.payload, t.event.c.actor_report_id, t.event.c.audience).where(
                t.event.c.kind == "credential_revoked"
            )
        ).all()
        assert [(e.payload["reason"], e.actor_report_id) for e in said] == [
            ("suspended", made["id"])
        ]
        assert said[0].audience == [f"member:{agent.id}", "trust:owner"]
    login = factory.login_handle(make_client(), "pat")
    wrong = factory.login_handle(make_client(), "pat", "not the password")
    assert (login.status_code, login.json()) == (wrong.status_code, wrong.json())

    # Its memberships act as paused (§5.3).
    members = owner.get(f"/projects/{PROJECT}/members").json()["items"]
    shown = next(m for m in members if m["handle"] == "pat")
    assert shown["presence"] == "paused"
    assert shown["paused"]["reason"] == "account suspended"

    # A dismiss lifts holds, never a suspension: that is the operator's.
    assert resolve(team, made["id"], "dismiss").status_code == 200
    assert factory.login_handle(make_client(), "pat").status_code == 401
    with migrated.begin() as conn:
        assert moderation.unsuspend(conn, pat.id)
    back = factory.login_handle(make_client(), "pat")
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


@contextmanager
def transactions(engine: Engine) -> Iterator[list[list[str]]]:
    """The statements each transaction on `engine` runs inside the block."""
    seen: list[list[str]] = []

    def begin(conn: Any) -> None:
        seen.append([])

    def statement(conn: Any, cursor: Any, text: str, *args: Any) -> None:
        if seen:
            seen[-1].append(text)

    event.listen(engine, "begin", begin)
    event.listen(engine, "before_cursor_execute", statement)
    try:
        yield seen
    finally:
        event.remove(engine, "begin", begin)
        event.remove(engine, "before_cursor_execute", statement)


def test_an_exchange_takes_the_account_lock_before_any_other(
    team: dict[str, Any], make_client: ClientFactory, migrated: Engine
) -> None:
    """A join exchange and a runner pairing lock the issuing account first, the order a
    suspension and a deletion take (§2.9), before their link's or enrollment's rows."""
    owner = team["owner"]
    created, enrolled = flow.join(owner, "maity"), runners.enroll(owner)
    exchanges: list[tuple[Callable[[Any, dict[str, Any]], Any], dict[str, Any], str]] = [
        (flow.exchange, created, "join_link"),
        (runners.exchange, enrolled, "runner_enrollment"),
    ]
    for exchange, made, row in exchanges:
        with transactions(migrated) as seen:
            assert exchange(make_client(), made).status_code == 201
        [statements] = [s for s in seen if any(f"UPDATE {row}" in x for x in s)]
        first = next(i for i, x in enumerate(statements) if locking(x) and "account_lock" not in x)
        assert any("FROM account_lock" in x for x in statements[:first]), statements


def test_a_suspension_locks_projects_before_the_human(
    team: dict[str, Any], make_client: ClientFactory, migrated: Engine
) -> None:
    """The account lock first (§2.9); then the credentials, which lock their projects;
    the human's sessions and row last, the order project work takes (project, then
    human)."""
    pat = team["pat"]
    flow.agent(make_client, pat, PROJECT)
    runners.paired(make_client, pat)
    with transactions(migrated) as seen, event_log.transaction(migrated) as conn:
        moderation.suspend(conn, pat.id, "rpt-000000000000")
    [statements] = [s for s in seen if any("UPDATE human_session" in x for x in s)]
    revoked = [i for i, x in enumerate(statements) if x.startswith("UPDATE credential")]
    paired = [i for i, x in enumerate(statements) if x.startswith("UPDATE runner_credential")]
    human = [i for i, x in enumerate(statements) if x.startswith("UPDATE human")]
    assert revoked and paired and human, statements
    # SQLite renders no lock clause: the account lock's read is what comes first.
    first = next(i for i, x in enumerate(statements) if locking(x) and "account_lock" not in x)
    assert "FROM account_lock" in statements[0], statements
    assert any("FROM account_lock" in x and "FOR UPDATE" in x for x in statements[:first]) or (
        migrated.dialect.name == "sqlite"
    ), statements
    assert max(revoked + paired) < min(human), statements


def test_an_agent_is_reported_by_its_name_only_by_who_can_read_it(
    team: dict[str, Any], make_client: ClientFactory, migrated: Engine
) -> None:
    """No page outside a project shows an agent since the public swarm page went (§6.22): a
    stranger's report by its global name is `not_found`, a fellow member's is taken (§16.8)."""
    owner, stranger = team["owner"], team["stranger"]
    agent = flow.agent(make_client, owner)
    name = f"maintainer/{owner.get(f'/agents/{agent.id}').json()['handle']}"
    assert report(stranger, {"type": "profile", "id": name}).status_code == 404
    made = report(team["pat"], {"type": "profile", "id": name})
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


def test_hide_isolates_the_agents_of_outsiders_of_an_unset_setting(
    team: dict[str, Any], migrated: Engine
) -> None:
    """§6.2: an unset `agent_owners` reads `members` once the project is not served, so the
    agents whose owners are no member are isolated by the hub."""
    owner = team["owner"]
    with migrated.connect() as conn:
        project_id = conn.execute(select(t.project.c.id)).scalar_one()
    lent = factory.agent(migrated, project_id, factory.human(migrated, "outside-owner")).agent_id
    assert owner.patch(f"/projects/{PROJECT}", {"public_page": "on"}).status_code == 200

    def isolated() -> Any:
        with migrated.connect() as conn:
            return conn.execute(select(t.membership).where(t.membership.c.agent_id == lent)).one()

    assert isolated().isolated_since is None  # `anyone` while the project has a page
    made = report(team["pat"], {"type": "project", "id": PROJECT}).json()
    assert resolve(team, made["id"], "hide", "spam page").status_code == 200
    row = isolated()
    assert row.isolated_since is not None and row.isolated_by == "hub"
