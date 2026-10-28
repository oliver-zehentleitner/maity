"""docs/api.md §5.1: `GET /me` for a human, with open requests per project."""

from __future__ import annotations

from typing import Any

from sqlalchemy import Engine, insert

from maity_hub import clock
from maity_hub import tables as t
from maity_hub.ids import new_id
from tests import factory
from tests.conftest import ClientFactory


def _request(engine: Engine, project_id: str, asked_by: int, **to: Any) -> None:
    status = to.pop("status", "open")
    with engine.begin() as conn:
        conn.execute(
            insert(t.request).values(
                id=new_id("request"),
                project_id=project_id,
                **{"class": "decision"},
                title="?",
                options=[],
                priority="normal",
                asked_by=asked_by,
                while_open="wait",
                status=status,
                created_at=clock.now(),
                **to,
            )
        )


def test_a_human_sees_every_membership_with_its_open_requests(
    make_client: ClientFactory, migrated: Engine
) -> None:
    owner = factory.human(migrated, "maintainer")
    maity = factory.project(migrated, "maity", name="Maity")
    sample = factory.project(migrated, "sample", name="Sample shop", state="freeze")
    other = factory.project(migrated, "other")  # not a member: never listed or counted
    me_maity = factory.membership(migrated, maity, "owner", human_id=owner)
    factory.membership(migrated, sample, "proxy", human_id=owner)
    agent = factory.agent(migrated, maity, owner)
    stranger = factory.agent(migrated, other, factory.human(migrated))

    _request(migrated, maity, agent.membership_id, to_kind="owner")
    _request(migrated, maity, agent.membership_id, to_kind="member", to_member=me_maity)
    _request(migrated, maity, agent.membership_id, to_kind="role", to_role="owner")
    _request(migrated, maity, agent.membership_id, to_kind="role", to_role="admin")  # not mine
    _request(migrated, maity, agent.membership_id, to_kind="owner", status="answered")
    _request(migrated, other, stranger.membership_id, to_kind="owner")
    _request(migrated, sample, agent.membership_id, to_kind="role", to_role="proxy")
    _request(migrated, sample, agent.membership_id, to_kind="owner")  # the proxy is not owner

    client = make_client()
    client.post("/api/v1/auth/login", json={"handle": "maintainer", "password": factory.PASSWORD})
    body = client.get("/api/v1/me").json()
    assert body["member"] == {
        "id": owner,
        "kind": "human",
        "handle": "maintainer",
        "display_name": "Human maintainer",
        "avatar_url": None,
        "avatar_source": None,
        "instance_admin": True,  # the earliest human (§16)
        "meat_proxy": False,  # §5.2
        "account_status": "active",  # §2.7.5
        "terms": None,  # made by the operator: nothing accepted (§2.7.2)
        "limit": None,  # no limit declared (§6.12)
    }
    assert body["projects"] == [
        {
            "slug": "maity",
            "full_name": "maintainer/maity",
            "name": "Maity",
            "state": "build",
            "role": "owner",
            "logo": {"available": False, "etag": None},
            "open_requests": 3,
        },
        {
            "slug": "sample",
            "full_name": "maintainer/sample",
            "name": "Sample shop",
            "state": "freeze",
            "role": "proxy",
            "logo": {"available": False, "etag": None},
            "open_requests": 1,
        },
    ]
    assert factory.at(body["server_time"])


def test_me_without_credentials_is_unauthenticated(make_client: ClientFactory) -> None:
    response = make_client().get("/api/v1/me")
    assert response.status_code == 401
    assert response.headers["Maity-Error"] == "unauthenticated"
