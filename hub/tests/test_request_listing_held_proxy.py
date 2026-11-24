"""docs/api.md §7 and §9.6 for the request listing (tsk-maw3n0h3j25s):
- a request held for an agent (`held`) is not its to read or find, so `to=all` leaves it out
  for that agent even under `requests:answer`, and the open-request counts leave it out too;
- under `to=me` a proxy also gets the open requests addressed to `owner`, which it relays
  (§2.3), in the listing and in the counts."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import Engine, select, update

from maity_hub import inbox
from maity_hub import tables as t
from maity_hub.access import Membership
from maity_hub.routes import overview
from tests import flow
from tests.conftest import ClientFactory
from tests.test_requests import answer, asked

LIST = "/projects/maintainer/maity/requests"


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    owner = flow.human(make_client, migrated)
    flow.project(owner, "maity")
    return owner


def listed(who: Any, query: str) -> list[str]:
    got = who.get(f"{LIST}?{query}")
    assert got.status_code == 200, got.text
    return [r["id"] for r in got.json()["items"]]


def counts(engine: Engine, member_id: str) -> dict[str, Any]:
    agent = member_id.startswith("agt-")
    column = t.membership.c.agent_id if agent else t.membership.c.human_id
    with engine.connect() as conn:
        row = conn.execute(
            select(t.membership).where(column == member_id, t.membership.c.active.is_(True))
        ).one()
        project = conn.execute(select(t.project).where(t.project.c.id == row.project_id)).one()
        mine = Membership(project, row, "agent" if row.agent_id else "human")
        return overview.request_counts(conn, mine)


def hold_for(engine: Engine, request_id: str, agent_id: str) -> None:
    with engine.begin() as conn:
        conn.execute(update(t.request).where(t.request.c.id == request_id).values(held=[agent_id]))


# --- a request held for the caller -----------------------------------------------------------


def test_to_all_and_the_counts_leave_out_a_request_held_for_the_caller(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    admin = flow.agent(make_client, owner, role="admin")  # holds requests:answer
    worker = flow.agent(make_client, owner)
    request = asked(worker, to=admin.id)
    hold_for(migrated, request["id"], admin.id)
    assert request["id"] not in listed(admin, "to=all")
    assert counts(migrated, admin.id)["open"] == 0


def test_to_all_and_the_counts_keep_a_request_held_for_someone_else(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    admin = flow.agent(make_client, owner, role="admin")
    worker = flow.agent(make_client, owner)
    request = asked(worker, to=admin.id)
    hold_for(migrated, request["id"], admin.id)
    assert request["id"] in listed(owner, "to=all")
    assert counts(migrated, owner.id)["open"] == 1


# --- a proxy and the requests addressed to the owner -----------------------------------------


def test_a_proxy_finds_the_open_requests_to_the_owner_under_to_me(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    proxy = flow.agent(make_client, owner, role="proxy")
    worker = flow.agent(make_client, owner)
    request = asked(worker, to="owner")
    assert request["id"] in listed(proxy, "to=me")
    assert counts(migrated, proxy.id)["to_me"] == 1


def test_a_proxy_finds_a_request_to_trust_owner_too(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    proxy = flow.agent(make_client, owner, role="proxy")
    worker = flow.agent(make_client, owner)
    request = asked(worker, to="trust:owner")
    assert request["id"] in listed(proxy, "to=me")
    assert counts(migrated, proxy.id)["to_me"] == 1


def test_a_proxy_does_not_hold_what_it_relays_so_it_cannot_forward_it(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    proxy = flow.agent(make_client, owner, role="proxy")
    worker = flow.agent(make_client, owner)
    request = asked(worker, to="owner")
    refused = proxy.post(f"{LIST}/{request['id']}/forward", {"to": "trust:admin"})
    assert refused.status_code == 403, refused.text
    assert refused.json()["error"]["details"]["reason"] == "not_request_holder"
    assert request["id"] in listed(owner, "to=me")  # still the owner's to answer


def test_a_bridge_consent_is_not_the_proxys_to_relay_anywhere(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    proxy = flow.agent(make_client, owner, role="proxy")
    worker = flow.agent(make_client, owner)
    request = asked(worker, to="owner")
    with migrated.begin() as conn:
        conn.execute(
            update(t.request)
            .where(t.request.c.id == request["id"])
            .values(proposal={"kind": "bridge_project"})
        )
    assert request["id"] not in listed(proxy, "to=me")
    assert counts(migrated, proxy.id)["to_me"] == 0
    with migrated.connect() as conn:  # what /me and the notifications count
        row = conn.execute(select(t.membership).where(t.membership.c.agent_id == proxy.id)).one()
        assert inbox.open_requests(conn, row.id) == 0


def test_the_counts_python_branch_reads_the_status_for_a_proxy(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    """A request held for someone else is one the counts decide in Python
    (`request_sql.DECIDED_BY`)."""
    proxy = flow.agent(make_client, owner, role="proxy")
    worker = flow.agent(make_client, owner)
    other = flow.agent(make_client, owner)
    request = asked(worker, to="owner")
    hold_for(migrated, request["id"], other.id)
    assert counts(migrated, proxy.id)["to_me"] == 1


def test_a_request_the_owner_forwarded_leaves_the_proxys_to_me(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    proxy = flow.agent(make_client, owner, role="proxy")
    admin = flow.agent(make_client, owner, role="admin")
    worker = flow.agent(make_client, owner)
    request = asked(worker, to="owner")
    moved = owner.post(f"{LIST}/{request['id']}/forward", {"to": admin.id})
    assert moved.status_code == 200, moved.text
    assert request["id"] not in listed(proxy, "to=me")
    assert counts(migrated, proxy.id)["to_me"] == 0


def test_another_admin_agent_and_a_closed_request_are_not_the_proxys_to_me(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    proxy = flow.agent(make_client, owner, role="proxy")
    admin = flow.agent(make_client, owner, role="admin")
    worker = flow.agent(make_client, owner)
    request = asked(worker, to="owner")
    assert request["id"] not in listed(admin, "to=me")  # only the proxy relays
    assert counts(migrated, admin.id)["to_me"] == 0
    assert answer(owner, request, text="go").status_code == 200
    assert request["id"] not in listed(proxy, "to=me&status=all")  # open ones only
