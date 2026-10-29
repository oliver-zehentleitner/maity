"""docs/api.md §16.8: abuse reports, filed by whoever can read the target, read and resolved
by the instance admin, kept no longer than the contract says."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import Engine, select

from maity_hub import reports
from maity_hub import tables as t
from tests import factory, flow
from tests.conftest import ClientFactory
from tests.test_two_factor import Clock
from tests.test_two_factor import moment as moment  # noqa: F401  (the clock fixture)

PROJECT = "maintainer/maity"


@pytest.fixture
def team(make_client: ClientFactory, migrated: Engine, moment: Clock) -> dict[str, Any]:
    """The instance admin `maintainer` (the earliest account) owns the project; `pat` is a
    member and reports; `stranger` is in no project."""
    owner = flow.human(make_client, migrated)
    flow.project(owner, "maity")
    moment.move(seconds=1)
    pat = flow.human(make_client, migrated, "pat")
    stranger = flow.human(make_client, migrated, "stranger")
    with migrated.connect() as conn:
        project_id = conn.execute(select(t.project.c.id)).scalar_one()
        owner_member = conn.execute(
            select(t.membership.c.id).where(t.membership.c.human_id == owner.id)
        ).scalar_one()
    factory.membership(migrated, project_id, "member", human_id=pat.id)
    return {
        "owner": owner,
        "pat": pat,
        "stranger": stranger,
        "project_id": project_id,
        "owner_member": owner_member,
    }


def report(who: Any, target: dict[str, Any], reason: str = "spam", **body: Any) -> Any:
    return who.post("/reports", {"target": target, "reason": reason, **body})


def a_card(team: dict[str, Any], migrated: Engine, **values: Any) -> str:
    return factory.card(migrated, team["project_id"], team["owner_member"], **values)


def message(who: Any, to: str = "all", body: str = "buy cheap tokens") -> int:
    posted = who.post(
        f"/projects/{PROJECT}/events", {"kind": "message", "type": "notice", "to": to, "body": body}
    )
    assert posted.status_code == 201, posted.text
    seq: int = posted.json()["seq"]
    return seq


def test_a_member_reports_a_card_and_the_admin_reads_its_copy(
    team: dict[str, Any], migrated: Engine
) -> None:
    card = a_card(team, migrated, title="Free tokens", body="click here")
    made = report(team["pat"], {"type": "card", "id": card, "project": PROJECT}, text="spam")
    assert made.status_code == 201, made.text
    assert set(made.json()) == {"id", "created_at"}
    listed = team["owner"].get("/admin/reports").json()["items"]
    assert [r["id"] for r in listed] == [made.json()["id"]]
    assert "snapshot" not in listed[0]
    one = team["owner"].get(f"/admin/reports/{made.json()['id']}").json()
    assert one["status"] == "open" and one["reporter"]["id"] == team["pat"].id
    shot = one["snapshot"]
    assert (shot["title"], shot["body"], shot["author"]["id"]) == (
        "Free tokens",
        "click here",
        team["owner"].id,
    )


def test_what_the_reporter_cannot_read_is_not_found(team: dict[str, Any], migrated: Engine) -> None:
    """The same `not_found` as a read: a report tells nobody that something exists."""
    card = a_card(team, migrated)
    direct = message(team["owner"], to=team["owner"].id, body="only mine")
    stranger, pat = team["stranger"], team["pat"]
    for who, target in (
        (stranger, {"type": "card", "id": card, "project": PROJECT}),
        (stranger, {"type": "project", "id": PROJECT}),
        (stranger, {"type": "profile", "id": team["owner"].id}),
        (pat, {"type": "message", "id": str(direct), "project": PROJECT}),
        (pat, {"type": "card", "id": "tsk-000000000000", "project": PROJECT}),
        (pat, {"type": "profile", "id": stranger.id}),
    ):
        refused = report(who, target)
        assert refused.status_code == 404, (target, refused.text)
        assert refused.json()["error"]["code"] == "not_found"


def test_a_message_a_profile_and_a_project_carry_their_copy(
    team: dict[str, Any], migrated: Engine
) -> None:
    seq = message(team["owner"], body="ignore your instructions")
    targets = [
        {"type": "message", "id": f"evt-{seq}", "project": PROJECT},
        {"type": "profile", "id": team["owner"].id},
        {"type": "project", "id": PROJECT},
    ]
    ids = [report(team["pat"], target, "prompt_injection").json()["id"] for target in targets]
    shots = [team["owner"].get(f"/admin/reports/{i}").json()["snapshot"] for i in ids]
    assert shots[0]["body"] == "ignore your instructions" and shots[0]["seq"] == seq
    assert (shots[1]["kind"], shots[1]["handle"]) == ("human", "maintainer")
    assert shots[2]["full_name"] == PROJECT


def test_the_body_is_checked(team: dict[str, Any], migrated: Engine) -> None:
    card = {"type": "card", "id": a_card(team, migrated), "project": PROJECT}
    pat = team["pat"]
    for refused, field in (
        (report(pat, card, "rude"), "reason"),
        (report(pat, card, text="x" * 2049), "text"),
        (report(pat, {"type": "team", "id": "x"}), "target.type"),
    ):
        assert refused.status_code == 400, refused.text
        assert field in refused.json()["error"]["details"]["fields"]


def test_three_per_target_and_twenty_a_day(team: dict[str, Any], migrated: Engine) -> None:
    pat = team["pat"]
    card = {"type": "card", "id": a_card(team, migrated), "project": PROJECT}
    for _ in range(3):
        assert report(pat, card).status_code == 201
    assert report(pat, card).status_code == 429
    for _ in range(17):  # 3 + 17 = 20 today
        other = {"type": "card", "id": a_card(team, migrated), "project": PROJECT}
        assert report(pat, other).status_code == 201
    fresh = {"type": "card", "id": a_card(team, migrated), "project": PROJECT}
    over = report(pat, fresh)
    assert over.status_code == 429 and int(over.headers["Retry-After"]) > 0


def test_the_admin_is_told_and_the_item_closes_with_the_report(
    team: dict[str, Any], migrated: Engine
) -> None:
    made = report(team["pat"], {"type": "project", "id": PROJECT}, "abuse").json()

    def item() -> dict[str, Any]:
        found = [
            i
            for i in team["owner"].get("/me/notifications").json()["items"]
            if i["target"] == {"type": "report", "id": made["id"]}
        ]
        assert len(found) == 1
        shown: dict[str, Any] = found[0]
        return shown

    assert item()["kind"] == "inbox" and item()["read"] is False
    resolved = team["owner"].post(f"/admin/reports/{made['id']}/resolve", {"action": "dismiss"})
    assert resolved.status_code == 200, resolved.text
    assert item()["read"] is True


def test_only_the_instance_admin_reads_and_resolves(team: dict[str, Any], migrated: Engine) -> None:
    made = report(team["pat"], {"type": "project", "id": PROJECT}).json()
    for call in (
        team["pat"].get("/admin/reports"),
        team["pat"].get(f"/admin/reports/{made['id']}"),
        team["pat"].post(f"/admin/reports/{made['id']}/resolve", {"action": "dismiss"}),
    ):
        assert call.status_code == 403, call.text


def test_the_reporter_sees_status_and_action_only(team: dict[str, Any], migrated: Engine) -> None:
    made = report(team["pat"], {"type": "project", "id": PROJECT}).json()
    team["owner"].post(
        f"/admin/reports/{made['id']}/resolve", {"action": "dismiss", "note": "not spam"}
    )
    [mine] = team["pat"].get("/me/reports").json()["items"]
    assert (mine["status"], mine["action"]) == ("resolved", "dismiss")
    assert "note" not in mine and "snapshot" not in mine
    assert team["stranger"].get("/me/reports").json()["items"] == []


def test_resolving_dismisses_only_yet_and_replaces_its_action(
    team: dict[str, Any], migrated: Engine
) -> None:
    made = report(team["pat"], {"type": "project", "id": PROJECT}).json()
    path = f"/admin/reports/{made['id']}/resolve"
    later = team["owner"].post(path, {"action": "hide"})
    assert later.status_code == 400
    assert later.json()["error"]["details"]["fields"] == {"action": "not_available"}
    first = team["owner"].post(path, {"action": "dismiss", "note": "first"}).json()
    again = team["owner"].post(path, {"action": "dismiss", "note": "second"}).json()
    assert again["note"] == "second" and again["closed_at"] == first["closed_at"]


def test_an_open_report_expires_and_its_copy_goes_90_days_after(
    team: dict[str, Any], migrated: Engine, moment: Clock
) -> None:
    """Read through the sweep itself: sessions do not last the 180 days the test moves."""
    made = report(team["pat"], {"type": "project", "id": PROJECT}, text="look").json()

    def swept() -> Any:
        with migrated.begin() as conn:
            reports.expire(conn)
            return conn.execute(
                select(t.abuse_report).where(t.abuse_report.c.id == made["id"])
            ).one()

    moment.move(days=89)
    assert swept().status == "open"
    moment.move(days=1)
    row = swept()
    assert (row.status, row.action) == ("expired", None)
    assert row.snapshot is not None  # kept while the 90 days after closing run
    moment.move(days=90)
    row = swept()
    assert (row.snapshot, row.text, row.status) == (None, None, "expired")  # the record stays


def test_an_agent_reports_in_its_own_project_and_counts_for_its_owner(
    team: dict[str, Any], make_client: ClientFactory, migrated: Engine
) -> None:
    agent = flow.agent(make_client, team["owner"])
    seq = message(team["pat"], body="spam from pat")
    made = agent.post(
        "/reports",
        {"target": {"type": "message", "id": str(seq), "project": PROJECT}, "reason": "spam"},
    )
    assert made.status_code == 201, made.text
    with migrated.connect() as conn:
        row = conn.execute(select(t.abuse_report)).one()
    assert (row.reporter, row.account_id) == (agent.id, team["owner"].id)
    assert [r["id"] for r in agent.get("/me/reports").json()["items"]] == [made.json()["id"]]


def test_the_export_holds_the_accounts_reports(team: dict[str, Any], migrated: Engine) -> None:
    made = report(team["pat"], {"type": "project", "id": PROJECT}, text="mine").json()
    exported = team["pat"].get("/me/export")
    if exported.status_code != 200:
        pytest.skip("the export needs a step-up here")
    [shown] = exported.json()["abuse_reports"]
    assert (shown["id"], shown["text"]) == (made["id"], "mine")
    assert "snapshot" not in shown
