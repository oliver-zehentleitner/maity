"""docs/api.md §2.3 "The steward": built on the expert, with the coder's scopes; it keeps the
project's reasoning complete and is never routed a card, a substitute or a card's `needs`."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import Engine, select

from maity_hub import rules
from maity_hub import tables as t
from tests import flow
from tests.conftest import ClientFactory

PROJECT = "/projects/maintainer/maity"


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    owner = flow.human(make_client, migrated)
    flow.project(owner, "maity")
    return owner


@pytest.fixture
def steward(make_client: ClientFactory, owner: flow.Human) -> flow.Agent:
    return flow.agent(make_client, owner, role="steward", areas=["context/"])


def _card(who: Any, **body: Any) -> Any:
    return who.post(f"{PROJECT}/tasks", {"title": "A card", "kind": "task", **body})


def _fields(response: Any) -> dict[str, Any]:
    assert response.status_code == 400, response.text
    fields: dict[str, Any] = response.json()["error"]["details"]["fields"]
    return fields


def test_the_steward_is_built_in_with_the_coders_scopes(owner: flow.Human) -> None:
    """§2.3: the role table's row, its guide and its scopes, after `expert`."""
    builtin = owner.get(f"{PROJECT}/roles").json()["builtin"]
    names = [role["name"] for role in builtin]
    assert names.index("steward") == names.index("expert") + 1
    [steward] = [role for role in builtin if role["name"] == "steward"]
    [coder] = [role for role in builtin if role["name"] == "coder"]
    assert steward["scopes"] == coder["scopes"]
    assert steward["guide"].startswith("You keep the project's reasoning complete")


def test_a_steward_notes_opens_cards_and_asks(owner: flow.Human, steward: flow.Agent) -> None:
    """The expert's scopes could not post a note, open a card or file a request; the
    steward's, the coder's, can (§2.3 "The steward", "How it nudges")."""
    card = _card(owner).json()["id"]
    noted = steward.post(f"{PROJECT}/tasks/{card}/notes", {"body": "Which entry says why?"})
    assert noted.status_code == 201, noted.text
    opened = _card(steward, title="The entry for the cache decision", area="hub/")
    assert opened.status_code == 201, opened.text
    asked = steward.post(
        f"{PROJECT}/requests", {"class": "info", "title": "Confirm the entry?", "to": "owner"}
    )
    assert asked.status_code == 201, asked.text


def test_a_join_fills_the_stewards_sources(owner: flow.Human, steward: flow.Agent) -> None:
    """§2.3: a join that gives the role fills `expert_for` and `expert_sources`."""
    [shown] = [m for m in owner.get(f"{PROJECT}/members").json()["items"] if m["id"] == steward.id]
    assert shown["expert_for"] == "`context/`: the project's reasoning"
    assert shown["expert_sources"] == ["context/"]


def test_the_fields_stay_between_expert_and_steward_and_go_with_any_other_role(
    owner: flow.Human, steward: flow.Agent
) -> None:
    """§6.2: the fields exist on `expert` and `steward`; a change between the two keeps them."""
    path = f"{PROJECT}/members/{steward.id}"
    changed = owner.patch(path, {"expert_sources": ["context/", "hub/context/"]})
    assert changed.status_code == 200, changed.text
    expert = owner.patch(path, {"role": "expert"})
    assert expert.status_code == 200, expert.text
    assert expert.json()["expert_sources"] == ["context/", "hub/context/"]
    back = owner.patch(path, {"role": "steward"})
    assert back.json()["expert_sources"] == ["context/", "hub/context/"]
    coder = owner.patch(path, {"role": "coder"})
    assert (coder.json()["expert_for"], coder.json()["expert_sources"]) == (None, [])


def test_area_routing_skips_the_steward(owner: flow.Human, steward: flow.Agent) -> None:
    """§2.3, §6.2: the steward owns `context/` here and is still never a card's routed owner."""
    created = _card(owner, area="context/trust.md")
    assert created.status_code == 201, created.text
    assert created.json()["assigned_to"] == owner.id  # "/" is the owner's


def test_no_card_needs_the_steward(owner: flow.Human) -> None:
    """§6.4: `needs: steward` is `invalid`."""
    assert _fields(_card(owner, needs="steward")) == {"needs": "unknown"}


def test_role_steward_is_no_substitute(
    make_client: ClientFactory, owner: flow.Human, steward: flow.Agent
) -> None:
    """§6.12: `role:steward` in `substitutes` is `invalid`."""
    covered = flow.agent(make_client, owner)
    refused = owner.patch(
        f"{PROJECT}/members/{covered.id}",
        {"availability_policy": {"on_unavailable": "substitute", "substitutes": ["role:steward"]}},
    )
    assert _fields(refused) == {"availability_policy.substitutes": "steward"}


def test_a_steward_named_by_id_is_skipped_when_cover_runs(
    make_client: ClientFactory, owner: flow.Human, steward: flow.Agent, migrated: Engine
) -> None:
    """§2.3 "The steward": one named by id is skipped in the cover order."""
    from maity_hub import cover

    covered, other = flow.agent(make_client, owner), flow.agent(make_client, owner)
    named = owner.patch(
        f"{PROJECT}/members/{covered.id}",
        {
            "availability_policy": {
                "on_unavailable": "substitute",
                "substitutes": [steward.id, other.id],
            }
        },
    )
    assert named.status_code == 200, named.text
    with migrated.begin() as conn:
        project = conn.execute(select(t.project).where(t.project.c.slug == "maity")).one()
        row = conn.execute(select(t.membership).where(t.membership.c.agent_id == covered.id)).one()
        order = [m.agent_id for m in cover.cover_order(conn, project, row)]
    assert order == [other.id]


def test_no_project_role_is_named_steward_or_built_on_it(owner: flow.Human) -> None:
    """§2.3: the name is the built-in role's, and the steward is no base."""
    named = flow.put_roles(owner, PROJECT, [{"name": "steward", "base": "writer"}])
    assert _fields(named) == {"custom[0].name": "reserved"}
    based = flow.put_roles(owner, PROJECT, [{"name": "keeper", "base": "steward"}])
    assert _fields(based) == {"custom[0].base": "unknown"}


def test_the_steward_is_not_offered_to_outsiders(owner: flow.Human) -> None:
    """§6.1: `policy.outside_roles` may not name it."""
    refused = owner.patch(
        PROJECT, {"policy": {"outside_roles": ["coder", "steward"]}, "reason": "outsiders"}
    )
    assert _fields(refused) == {"outside_roles": "role_not_allowed"}


def test_the_stewards_rules_carry_its_line_and_the_narrowed_policy_sentence(
    owner: flow.Human, steward: flow.Agent, make_client: ClientFactory
) -> None:
    """§6.9: the steward line for a steward only; `steward_writes` as one policy sentence."""
    coder = flow.agent(make_client, owner)
    text = steward.get(f"{PROJECT}/rules").text
    assert f"## Stewarding\n\n{rules.STEWARD}" in text
    assert rules.STEWARD not in coder.get(f"{PROJECT}/rules").text
    cards_only = (  # docs/api.md §2.3 "The steward", "No substitute", word for word
        "The Keep the Why steward asks the authors of missing `context/` entries and opens "
        "cards for them; it writes no entry itself."
    )
    written = (
        "The Keep the Why steward asks the authors of missing `context/` entries first; it "
        "writes an entry itself, in its own pull request, only where no author can."
    )
    assert f"- {cards_only}" in text  # the default
    changed = owner.patch(
        PROJECT, {"policy": {"steward_writes": "self"}, "reason": "the steward may write"}
    )
    assert changed.status_code == 200, changed.text
    assert f"- {written}" in steward.get(f"{PROJECT}/rules").text
