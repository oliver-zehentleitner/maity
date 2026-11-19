"""docs/api.md §3.2 item 2: the join page says "You will read and write this project's
restricted texts." when the restricted-access set (§6.1) would hold the membership the
exchange creates, resolved when the page is served."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import Engine, update

from maity_hub import clock
from maity_hub import tables as t
from tests import factory, flow
from tests.conftest import ClientFactory
from tests.test_restricted_text import _project, _set

PROJECT = "/projects/maintainer/maity"
JOINS = f"{PROJECT}/joins"
SENTENCE = "You will read and write this project's restricted texts."


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    owner = flow.human(make_client, migrated)
    flow.project(owner, "maity")
    return owner


def _join(who: flow.Human, **body: Any) -> dict[str, Any]:
    body.setdefault("agent", {"handle": f"agent-{flow._n()}", "display_name": "An agent"})
    created = who.post(JOINS, body)
    assert created.status_code == 201, created.text
    found: dict[str, Any] = created.json()
    return found


def _page(make_client: ClientFactory, created: dict[str, Any]) -> str:
    token = created["join_url"].rsplit("/", 1)[1]
    response = make_client().get(f"/join/{token}", headers={"Accept": "text/markdown"})
    assert response.status_code == 200, response.text
    return str(response.text)


def _says(make_client: ClientFactory, created: dict[str, Any]) -> bool:
    return SENTENCE in _page(make_client, created)


def test_nothing_without_a_setting_or_for_a_set_that_names_nobody(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    created = _join(owner)
    assert not _says(make_client, created)
    _set(migrated, "nobody_except", [])
    assert not _says(make_client, created)


def test_all_except_names_a_new_agent_while_its_owner_is_in_the_set(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    created = _join(owner)
    _set(migrated, "all_except", [])
    assert _says(make_client, created)
    # Evaluated when the page is served: the owner listed leaves the agent out.
    _set(migrated, "all_except", [owner.id])
    assert not _says(make_client, created)
    # A guest join enters no set, whatever the mode.
    _set(migrated, "all_except", [])
    assert not _says(make_client, _join(owner, trust="guest", role="coder"))


def test_nobody_except_names_only_a_listed_profile(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    flow.project(owner, "other")
    elsewhere = flow.agent(make_client, owner, "other")  # a profile, no member of maity
    existing = _join(owner, agent={"id": elsewhere.id})
    fresh = _join(owner)  # a new profile, made with the join: no list names its id
    _set(migrated, "nobody_except", [owner.id])
    assert (_says(make_client, existing), _says(make_client, fresh)) == (False, False)
    _set(migrated, "nobody_except", [elsewhere.id])
    assert (_says(make_client, existing), _says(make_client, fresh)) == (True, False)
    # Under all_except the listed profile is left out, the new one is not.
    _set(migrated, "all_except", [elsewhere.id])
    assert (_says(make_client, existing), _says(make_client, fresh)) == (False, True)


def test_nothing_while_the_owner_is_a_guest_or_no_active_member(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    anna = flow.human(make_client, migrated, "anna")
    project_id = _project(migrated).id
    anna_m = factory.membership(migrated, project_id, "coder", trust="admin", human_id=anna.id)
    flow.project(anna, "anna-side")
    profile = flow.agent(make_client, anna, "anna/anna-side")
    fresh, existing = _join(anna), _join(anna, agent={"id": profile.id})

    def owner_trust(**values: Any) -> None:
        with migrated.begin() as conn:
            conn.execute(update(t.membership).where(t.membership.c.id == anna_m).values(**values))

    _set(migrated, "all_except", [])
    assert _says(make_client, fresh)
    owner_trust(trust="guest")
    assert not _says(make_client, fresh)
    _set(migrated, "nobody_except", [profile.id])
    assert not _says(make_client, existing)
    owner_trust(trust="member")
    assert _says(make_client, existing)
    owner_trust(active=None, removed_at=clock.now())
    assert not _says(make_client, existing)
    _set(migrated, "all_except", [])
    assert not _says(make_client, fresh)


def test_nothing_for_an_agent_that_is_an_active_member_already(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    member = flow.agent(make_client, owner)
    # Room for a second instance first: the default max_instances is 1 (§6.17).
    raised = owner.patch(f"{PROJECT}/members/{member.id}", {"team": {"max_instances": 2}})
    assert raised.status_code == 200, raised.text
    _set(migrated, "all_except", [])
    again = _join(owner, agent={"id": member.id}, new_instance=True)
    instead = _join(owner, agent={"id": member.id}, replaces=member.instance)
    assert not _says(make_client, again)  # a new instance enters nothing (§6.17)
    assert not _says(make_client, instead)  # nor does a replacement
    _set(migrated, "nobody_except", [member.id])
    assert not _says(make_client, again)
    assert not _says(make_client, instead)
