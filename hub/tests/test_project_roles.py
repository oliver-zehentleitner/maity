"""docs/api.md §2.3 "Project roles": a project's own roles on a built-in base."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import Engine, select

from maity_hub import events, merged
from maity_hub import tables as t
from maity_hub.views import principal_id
from tests import flow
from tests.conftest import ClientFactory

BASE = "/projects/maintainer/maity"
LEGAL = {
    "name": "legal",
    "base": "reviewer",
    "description": "Checks licences",
    "guide": "You check",
}


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    owner = flow.human(make_client, migrated)
    flow.project(owner)
    return owner


def put(owner: flow.Human, custom: Any) -> Any:
    return owner.client.put(
        f"/api/v1{BASE}/roles", json={"custom": custom}, headers={"X-CSRF-Token": owner.csrf}
    )


def assign(owner: flow.Human, member_id: str, role: str) -> Any:
    return owner.patch(f"{BASE}/members/{member_id}", {"trust": "member", "role": role})


def test_the_list_is_put_whole_and_read_back_with_who_set_the_guide(
    owner: flow.Human, migrated: Engine
) -> None:
    assert owner.get(f"{BASE}/roles").json() == {"custom": []}
    response = put(owner, [LEGAL, {"name": "translator", "base": "writer"}])
    assert response.status_code == 200, response.text
    expected = [
        {**LEGAL, "guide_by": "maintainer"},
        {"name": "translator", "base": "writer", "description": "", "guide": "", "guide_by": None},
    ]
    assert response.json() == {"custom": expected}
    assert owner.get(f"{BASE}/roles").json() == {"custom": expected}
    with migrated.connect() as conn:
        [changed] = conn.execute(
            select(t.event).where(t.event.c.kind == "policy_changed").order_by(t.event.c.seq)
        ).all()
    assert changed.payload["fields"] == ["roles"]
    assert changed.payload["new"] == expected
    # The same list again changes nothing: no second event.
    assert put(owner, [LEGAL, {"name": "translator", "base": "writer"}]).status_code == 200
    with migrated.connect() as conn:
        kinds = conn.execute(select(t.event.c.kind)).scalars().all()
    assert kinds.count("policy_changed") == 1


@pytest.mark.parametrize(
    ("custom", "fields"),
    [
        ([{"name": "coder", "base": "coder"}], {"custom[0].name": "reserved"}),
        ([{"name": "owner", "base": "coder"}], {"custom[0].name": "reserved"}),
        ([{"name": "red-team", "base": "tester"}], {"custom[0].name": "reserved"}),
        ([{"name": "Legal", "base": "coder"}], {"custom[0].name": "format"}),
        ([{"name": "l", "base": "coder"}], {"custom[0].name": "format"}),
        ([{"name": "legal", "base": "proxy"}], {"custom[0].base": "unknown"}),
        ([{"name": "legal", "base": "manager"}], {"custom[0].base": "unknown"}),
        ([{"name": "legal", "base": "purple-team"}], {"custom[0].base": "unknown"}),
        ([LEGAL, LEGAL], {"custom[1].name": "duplicate"}),
        ([{**LEGAL, "guide": "x" * 501}], {"custom[0].guide": "too_long"}),
        ([{**LEGAL, "description": "x" * 201}], {"custom[0].description": "too_long"}),
        ([{**LEGAL, "colour": "red"}], {"custom[0].colour": "unknown_field"}),
        ([{"name": f"role-{i}", "base": "coder"} for i in range(13)], {"custom": "too_many"}),
    ],
)
def test_the_list_is_checked(owner: flow.Human, custom: Any, fields: dict[str, str]) -> None:
    response = put(owner, custom)
    assert response.status_code == 400, response.text
    assert response.json()["error"]["details"]["fields"] == fields


def test_only_a_human_with_project_admin_puts_the_list(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    agent = flow.agent(make_client, owner, trust="admin", role="coder")
    refused = agent.client.put(
        f"/api/v1{BASE}/roles", json={"custom": [LEGAL]}, headers=agent.auth | agent.key()
    )
    assert refused.status_code in (401, 403), refused.text
    assert agent.get(f"{BASE}/roles").status_code == 200  # every member reads it


def test_a_project_role_is_assigned_and_has_exactly_its_bases_scopes(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    put(owner, [LEGAL, {"name": "community", "base": "coder"}])
    agent = flow.agent(make_client, owner)
    assert assign(owner, agent.id, "nope").json()["error"]["details"]["fields"] == {
        "role": "unknown"
    }
    view = assign(owner, agent.id, "legal").json()
    assert (view["role"], view["role_base"]) == ("legal", "reviewer")
    scopes = agent.resume().json()["membership"]["scopes"]
    assert "tasks:review" in scopes and "releases:write" in scopes
    view = assign(owner, agent.id, "community").json()
    assert (view["role"], view["role_base"]) == ("community", "coder")
    assert "tasks:review" not in agent.resume().json()["membership"]["scopes"]


def test_a_join_and_an_invitation_take_a_project_role(owner: flow.Human) -> None:
    put(owner, [LEGAL])
    join = owner.post(
        f"{BASE}/joins",
        {"agent": {"handle": "lawyer", "display_name": "L"}, "trust": "member", "role": "legal"},
    )
    assert join.status_code == 201, join.text
    invited = owner.post(f"{BASE}/invitations", {"role": "legal"})
    assert invited.status_code == 201, invited.text
    unknown = owner.post(f"{BASE}/invitations", {"role": "nope"})
    assert unknown.json()["error"]["details"]["fields"] == {"role": "unknown"}


def test_a_role_in_use_cannot_be_removed(owner: flow.Human, make_client: ClientFactory) -> None:
    put(owner, [LEGAL])
    agent = flow.agent(make_client, owner)
    assign(owner, agent.id, "legal")
    refused = put(owner, [])
    assert refused.status_code == 409, refused.text
    details = refused.json()["error"]["details"]
    assert (details["reason"], details["role"], details["uses"]) == (
        "role_in_use",
        "legal",
        ["membership"],
    )
    assign(owner, agent.id, "coder")
    asked = owner.post(f"{BASE}/requests", {"class": "decision", "title": "A", "to": "role:legal"})
    assert asked.status_code == 201, asked.text
    assert put(owner, []).json()["error"]["details"]["uses"] == ["request"]


def test_a_role_moved_to_another_base_takes_its_members_along(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    put(owner, [LEGAL])
    agent = flow.agent(make_client, owner)
    assign(owner, agent.id, "legal")
    put(owner, [{**LEGAL, "base": "coder"}])
    assert owner.get(f"{BASE}/members/{agent.id}").json()["role_base"] == "coder"
    assert "tasks:review" not in agent.resume().json()["membership"]["scopes"]


def test_role_base_names_the_project_roles_on_it_but_their_own_token_only_them(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    """A request to `role:reviewer` reaches a project role on `reviewer` (§2.3, §8.2);
    one to `role:legal` only the project role's members, never the reviewers."""
    put(owner, [LEGAL])
    lawyer, reviewer = flow.agent(make_client, owner), flow.agent(make_client, owner)
    assign(owner, lawyer.id, "legal")
    assign(owner, reviewer.id, "reviewer")
    to_reviewer = owner.post(
        f"{BASE}/requests", {"class": "decision", "title": "R", "to": "role:reviewer"}
    ).json()["id"]
    to_legal = owner.post(
        f"{BASE}/requests", {"class": "decision", "title": "L", "to": "role:legal"}
    ).json()["id"]
    lawyer_sees = {r["id"] for r in lawyer.resume().json()["requests"]["to_answer"]}
    reviewer_sees = {r["id"] for r in reviewer.resume().json()["requests"]["to_answer"]}
    assert {to_reviewer, to_legal} <= lawyer_sees
    assert to_reviewer in reviewer_sees and to_legal not in reviewer_sees


def test_a_merge_wakes_a_project_role_on_the_done_authoritys_base(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    put(owner, [LEGAL, {"name": "community", "base": "coder"}])
    lawyer, helper = flow.agent(make_client, owner), flow.agent(make_client, owner)
    assign(owner, lawyer.id, "legal")
    assign(owner, helper.id, "community")
    with migrated.connect() as conn:
        project_id = conn.execute(select(t.project.c.id)).scalar_one()
    with events.transaction(migrated) as conn:
        events.emit(
            conn,
            project_id,
            "task_merged",
            merged.AUTHORITY["reviewer"],
            {"done_authority": "reviewer", "closed": False},
        )
    with migrated.connect() as conn:
        for agent, woken in ((lawyer, True), (helper, False)):
            row = conn.execute(
                select(t.membership).where(t.membership.c.agent_id == agent.id)
            ).one()
            who = principal_id(conn, row.id)
            assert who is not None
            rows, _ = events.read_waking(conn, project_id, row, who, 0, 50)
            assert ("task_merged" in {r.kind for r in rows}) == woken


def test_role_base_in_substitutes_takes_a_project_role_on_that_base(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    from maity_hub import cover

    put(owner, [LEGAL])
    covered, lawyer = flow.agent(make_client, owner), flow.agent(make_client, owner)
    assign(owner, lawyer.id, "legal")
    for substitutes, expected in ((["role:reviewer"], [lawyer.id]), (["role:legal"], [lawyer.id])):
        response = owner.patch(
            f"{BASE}/members/{covered.id}",
            {"availability_policy": {"on_unavailable": "substitute", "substitutes": substitutes}},
        )
        assert response.status_code == 200, response.text
        with migrated.connect() as conn:
            project = conn.execute(select(t.project)).one()
            row = conn.execute(
                select(t.membership).where(t.membership.c.agent_id == covered.id)
            ).one()
            assert [m.agent_id for m in cover.cover_order(conn, project, row)] == expected
    # The substitutes entry keeps the role in use.
    assign(owner, lawyer.id, "coder")
    assert put(owner, []).json()["error"]["details"]["uses"] == ["substitutes"]


def test_the_rules_carry_a_project_roles_guide_quoted_with_who_set_it(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    put(owner, [{**LEGAL, "guide": "You check licences.\nAsk before merging."}])
    agent = flow.agent(make_client, owner)
    assign(owner, agent.id, "legal")
    rules = agent.get(f"{BASE}/rules").text
    assert "Your role is legal, a project role with the scopes of a reviewer." in rules
    assert "Set by maintainer:\n\n> You check licences.\n> Ask before merging." in rules


def test_the_onboardings_check_in_with_keeps_the_role_in_use(owner: flow.Human) -> None:
    put(owner, [LEGAL])
    response = owner.patch(
        "/projects/maintainer/maity", {"settings": {"onboarding": {"check_in_with": "role:legal"}}}
    )
    assert response.status_code == 200, response.text
    assert put(owner, []).json()["error"]["details"]["uses"] == ["check_in_with"]
