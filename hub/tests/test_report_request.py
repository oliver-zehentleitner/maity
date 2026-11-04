"""docs/api.md §16.8, §7: a new abuse report reaches the instance admin as a personal request
without a project, which only resolving or expiry closes."""

from __future__ import annotations

from typing import Any

from sqlalchemy import Engine, insert, select

from maity_hub import reports
from maity_hub import tables as t
from maity_hub.db import downgrade, migrate
from tests import factory
from tests.test_migrations import _before
from tests.test_reports import PROJECT, report
from tests.test_reports import team as team  # noqa: F401  (the fixture)
from tests.test_two_factor import moment as moment  # noqa: F401  (the clock fixture)

REVISION = "20261104150000_report_request"


def admin_requests(team: dict[str, Any], status: str = "open") -> list[dict[str, Any]]:
    listed = team["owner"].get("/requests", params={"status": status})
    assert listed.status_code == 200, listed.text
    return [r for r in listed.json()["items"] if r.get("report")]


def test_a_new_report_files_a_request_to_the_instance_admin(team: dict[str, Any]) -> None:
    made = report(team["pat"], {"type": "project", "id": PROJECT}, "abuse", text="they insult")
    assert made.status_code == 201, made.text
    [request] = admin_requests(team)
    assert request["report"] == {"id": made.json()["id"], "reason": "abuse", "type": "project"}
    assert request["title"] == "Report: abuse — project"
    assert (request["personal"], request["filed_by"], request["class"]) == (True, "hub", "info")
    assert (request["project"], request["asked_by"], request["task_id"]) == (None, None, None)
    assert request["replies"] == [] and request["options"] == []
    assert "they insult" not in str(request)  # ids and kinds, never the content
    shown = team["owner"].get(f"/requests/{request['id']}")
    assert shown.status_code == 200 and shown.json()["report"] == request["report"]


def test_the_request_is_an_inbox_item_of_the_admin_only(team: dict[str, Any]) -> None:
    report(team["pat"], {"type": "project", "id": PROJECT})
    [request] = admin_requests(team)
    items = team["owner"].get("/me/notifications").json()["items"]
    assert [
        i["kind"] for i in items if i["target"] == {"type": "request", "id": request["id"]}
    ] == ["inbox"]
    for other in (team["pat"], team["stranger"]):
        assert other.get(f"/requests/{request['id']}").status_code == 404
        assert not [r for r in other.get("/requests").json()["items"] if r.get("report")]


def test_the_admin_cannot_answer_or_withdraw_it(team: dict[str, Any]) -> None:
    made = report(team["pat"], {"type": "project", "id": PROJECT}).json()
    [request] = admin_requests(team)
    for path, body in (("answer", {"text": "done"}), ("withdraw", {})):
        refused = team["owner"].post(f"/requests/{request['id']}/{path}", body)
        assert refused.status_code == 409, refused.text
        assert refused.json()["error"]["code"] == "resolve_the_report"
        assert refused.json()["error"]["details"] == {"report": made["id"]}
    assert admin_requests(team)[0]["status"] == "open"


def test_resolving_the_report_withdraws_the_request(team: dict[str, Any]) -> None:
    made = report(team["pat"], {"type": "project", "id": PROJECT}).json()
    before = team["owner"].get("/me/notifications").json()["counts"]["inbox"]
    resolved = team["owner"].post(f"/admin/reports/{made['id']}/resolve", {"action": "dismiss"})
    assert resolved.status_code == 200, resolved.text
    assert admin_requests(team) == []
    [closed] = admin_requests(team, "withdrawn")
    assert closed["report"]["id"] == made["id"]
    shown = team["owner"].get(f"/requests/{closed['id']}").json()
    assert shown["status"] == "withdrawn"
    assert team["owner"].get("/me/notifications").json()["counts"]["inbox"] == before - 1
    # Resolving again replaces the action and files nothing new.
    again = team["owner"].post(f"/admin/reports/{made['id']}/resolve", {"action": "hide"})
    assert again.status_code == 200, again.text
    assert admin_requests(team) == [] and len(admin_requests(team, "withdrawn")) == 1


def test_an_expired_report_withdraws_its_request(
    team: dict[str, Any], migrated: Engine, moment: Any
) -> None:
    made = report(team["pat"], {"type": "project", "id": PROJECT}).json()
    moment.move(days=90)
    with migrated.begin() as conn:
        reports.expire(conn)
    with migrated.connect() as conn:  # the sessions ended too: read the rows
        row = conn.execute(select(t.request).where(t.request.c.report_id == made["id"])).one()
    assert (row.status, row.withdraw_reason) == ("withdrawn", "expired")


def test_the_migration_files_a_request_for_each_open_report_and_takes_them_back(
    engine: Engine,
) -> None:
    from datetime import UTC, datetime

    migrate(engine, _before(engine, REVISION))
    admin = factory.human(engine, "admin")
    reporter = factory.human(engine, "pat")
    now = datetime(2026, 11, 1, tzinfo=UTC)
    with engine.begin() as conn:
        for report_id, status in (("rpt-open", "open"), ("rpt-done", "resolved")):
            conn.execute(
                insert(t.abuse_report).values(
                    id=report_id, reporter=reporter, account_id=reporter, target_type="profile",
                    target_id="agt-x", reason="spam", status=status, created_at=now,
                )
            )  # fmt: skip
    migrate(engine)
    with engine.connect() as conn:
        rows = conn.execute(
            select(t.request.c.id, t.request.c.report_id, t.request.c.to_human, t.request.c.title)
        ).all()
        records = conn.execute(
            select(t.account_record.c.human_id, t.account_record.c.data).where(
                t.account_record.c.type == "personal_request_created"
            )
        ).all()
    [(request_id, report_id, to_human, title)] = rows
    assert (report_id, to_human, title) == ("rpt-open", admin, "Report: spam — profile")
    assert [(r.human_id, r.data["request_id"]) for r in records] == [(admin, request_id)]
    downgrade(engine, _before(engine, REVISION))
    with engine.connect() as conn:
        assert conn.exec_driver_sql("SELECT count(*) FROM request").scalar() == 0


def test_the_migration_titles_the_request_in_the_admins_language(engine: Engine) -> None:
    from datetime import UTC, datetime

    from sqlalchemy import update

    migrate(engine, _before(engine, REVISION))
    admin = factory.human(engine, "admin")
    reporter = factory.human(engine, "pat")
    with engine.begin() as conn:
        conn.execute(update(t.human).where(t.human.c.id == admin).values(interface_language="de"))
        conn.execute(
            insert(t.abuse_report).values(
                id="rpt-open", reporter=reporter, account_id=reporter, target_type="project",
                target_id="prj-x", reason="abuse", status="open",
                created_at=datetime(2026, 11, 1, tzinfo=UTC),
            )
        )  # fmt: skip
    migrate(engine)
    with engine.connect() as conn:
        title = conn.execute(select(t.request.c.title)).scalar_one()
    assert title == "Meldung: abuse — project"
