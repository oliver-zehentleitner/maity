"""A human's language (docs/api.md §6.2, §5.2, §18.4): on the member view, in the resume
packet's peers, and in the texts the hub composes for that human."""

from __future__ import annotations

from typing import Any

from sqlalchemy import Engine, select

from maity_hub import tables as t
from tests import factory, flow
from tests.conftest import ClientFactory
from tests.test_notification_mail import ask, notifications, run, setup
from tests.test_notification_mail import at as at  # noqa: F401  (the clock fixture)

S = "/me/notification-settings"


def test_the_member_view_carries_the_humans_language(
    make_client: ClientFactory, migrated: Engine
) -> None:
    owner = flow.human(make_client, migrated)
    flow.project(owner)
    agent = flow.agent(make_client, owner)
    assert owner.get(f"/projects/maintainer/maity/members/{owner.id}").json()["language"] == "en"
    # Set without any address or mail settings (§18.4).
    assert owner.patch(S, {"email": {"language": "de"}}).status_code == 200
    listed = {m["id"]: m for m in agent.get("/projects/maintainer/maity/members").json()["items"]}
    assert listed[owner.id]["language"] == "de"
    assert "language" not in listed[agent.id]  # agents have no language of their own
    packet = agent.resume().json()
    assert [p["language"] for p in packet["peers"] if p["kind"] == "human"] == ["de"]


def test_a_member_patch_cannot_set_it(make_client: ClientFactory, migrated: Engine) -> None:
    owner = flow.human(make_client, migrated)
    flow.project(owner)
    response = owner.patch(f"/projects/maintainer/maity/members/{owner.id}", {"language": "de"})
    assert response.status_code == 400
    assert response.json()["error"]["details"]["fields"] == {"language": "read_only"}


def test_the_bell_speaks_the_humans_language(make_client: ClientFactory, migrated: Engine) -> None:
    owner = flow.human(make_client, migrated)
    flow.project(owner)
    agent = flow.agent(make_client, owner)
    owner.patch(S, {"email": {"language": "de"}})
    agent.post(
        "/projects/maintainer/maity/requests",
        {"class": "decision", "title": "Welche?", "to": "owner"},
    )
    items = owner.get("/me/notifications").json()["items"]
    titles = {i["kind"]: i["title"] for i in items}
    assert titles["inbox"].endswith("fragt: Welche?")
    assert titles["security"].startswith("Neue Anmeldung: ")


def test_a_removed_member_has_no_language(make_client: ClientFactory, migrated: Engine) -> None:
    owner = flow.human(make_client, migrated)
    flow.project(owner)
    with migrated.connect() as conn:
        project_id = conn.execute(select(t.project.c.id)).scalar_one()
    colleague = factory.human(migrated)
    factory.membership(migrated, project_id, "member", human_id=colleague)
    path = f"/projects/maintainer/maity/members/{colleague}"
    assert owner.get(path).json()["language"] == "en"
    removal = owner.delete(path)
    assert removal.status_code == 200, removal.text
    removed = removal.json()
    assert removed["removed_at"] and "language" not in removed


def test_the_mail_speaks_the_humans_language_too(
    make_client: ClientFactory, migrated: Engine, at: Any
) -> None:
    owner, agent = setup(make_client, migrated)
    assert owner.patch(S, {"email": {"language": "de"}}).status_code == 200
    ask(agent, "Welche?")
    at(minutes=3)  # past the two-minute window of an immediate item
    run(migrated)
    [mail] = notifications(migrated)
    assert mail.subject.startswith("[Maity] ") and "fragt: Welche?" in mail.subject
