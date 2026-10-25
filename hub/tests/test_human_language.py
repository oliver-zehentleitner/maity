"""A human's language (docs/api.md §6.2, §5.2, §18.4): on the member view, in the resume
packet's peers, and in the texts the hub composes for that human."""

from __future__ import annotations

from sqlalchemy import Engine

from tests import flow
from tests.conftest import ClientFactory

S = "/me/notification-settings"


def test_the_member_view_carries_the_humans_language(
    make_client: ClientFactory, migrated: Engine
) -> None:
    owner = flow.human(make_client, migrated)
    flow.project(owner)
    agent = flow.agent(make_client, owner)
    assert owner.get(f"/projects/maity/members/{owner.id}").json()["language"] == "en"
    # Set without any address or mail settings (§18.4).
    assert owner.patch(S, {"email": {"language": "de"}}).status_code == 200
    listed = {m["id"]: m for m in agent.get("/projects/maity/members").json()["items"]}
    assert listed[owner.id]["language"] == "de"
    assert "language" not in listed[agent.id]  # agents have no language of their own
    packet = agent.resume().json()
    assert [p["language"] for p in packet["peers"] if p["kind"] == "human"] == ["de"]


def test_a_member_patch_cannot_set_it(make_client: ClientFactory, migrated: Engine) -> None:
    owner = flow.human(make_client, migrated)
    flow.project(owner)
    response = owner.patch(f"/projects/maity/members/{owner.id}", {"language": "de"})
    assert response.status_code == 400
    assert response.json()["error"]["details"]["fields"] == {"language": "read_only"}


def test_the_bell_speaks_the_humans_language(make_client: ClientFactory, migrated: Engine) -> None:
    owner = flow.human(make_client, migrated)
    flow.project(owner)
    agent = flow.agent(make_client, owner)
    owner.patch(S, {"email": {"language": "de"}})
    agent.post("/projects/maity/requests", {"class": "decision", "title": "Welche?", "to": "owner"})
    card = owner.post("/projects/maity/tasks", {"title": "Meine"}).json()
    agent.post(f"/projects/maity/tasks/{card['id']}/claim", {})
    items = owner.get("/me/notifications").json()["items"]
    titles = {i["kind"]: i["title"] for i in items}
    assert titles["inbox"].endswith("fragt: Welche?")
    assert titles["card"].startswith(f"{card['id']} Meine: übernommen von ")
    assert titles["security"].startswith("Neue Anmeldung: ")
