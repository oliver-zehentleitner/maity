"""docs/api.md §19.4: a human's preferences — the text, its readers, proposals and their
review, the resume packet, the agent given its owner's text, the basis of a decision."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import Engine, select

from maity_hub import preferences
from maity_hub import tables as t
from maity_hub.events import transaction
from tests import factory, flow
from tests.conftest import ClientFactory


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    human = flow.human(make_client, migrated)
    flow.project(human)
    return human


def project_id(engine: Engine, slug: str = "maity") -> str:
    with engine.connect() as conn:
        found: str = conn.execute(
            select(t.project.c.id).where(t.project.c.slug == slug)
        ).scalar_one()
        return found


def second_human(
    make_client: ClientFactory, engine: Engine, handle: str = "second", role: str = "member"
) -> flow.Human:
    human = flow.human(make_client, engine, handle=handle)
    factory.membership(engine, project_id(engine), role=role, human_id=human.id)
    return human


def events(engine: Engine, kind: str) -> list[Any]:
    with engine.connect() as conn:
        return list(
            conn.execute(select(t.event).where(t.event.c.kind == kind).order_by(t.event.c.seq))
        )


def put(human: flow.Human, text: str, base: int | None = None) -> Any:
    body: dict[str, Any] = {"markdown": text}
    if base is not None:
        body["base_version"] = base
    return human.client.put(
        "/api/v1/me/preferences", json=body, headers={"X-CSRF-Token": human.csrf}
    )


# --- the human's own text -----------------------------------------------------------------------


def test_a_human_writes_versions_and_a_stale_base_is_a_conflict(
    owner: flow.Human, migrated: Engine
) -> None:
    empty = owner.get("/me/preferences").json()
    assert (empty["markdown"], empty["version"], empty["projects"]) == (
        "",
        0,
        [{"slug": "maity", "include": True}],
    )
    first = put(owner, "German in chat, English in code.")
    assert first.status_code == 200, first.text
    assert first.json()["version"] == 1
    assert first.json()["by"] == {"kind": "human", "id": owner.id, "handle": "maintainer"}
    assert (first.json()["proposed_by"], first.json()["confirmed_by"]) == (None, None)
    stale = put(owner, "something else", base=0)
    assert stale.status_code == 409
    assert stale.json()["error"]["details"] == {"current_version": 1, "base_version": 0}
    assert put(owner, "Propose, don't push.", base=1).json()["version"] == 2
    versions = owner.get("/me/preferences/versions").json()["items"]
    assert [v["version"] for v in versions] == [2, 1]
    assert put(owner, "x" * 8193).json()["error"]["details"]["fields"] == {"markdown": "too_long"}
    changed = events(migrated, "preferences_changed")
    assert [e.payload["version"] for e in changed] == [1, 2]
    assert "markdown" not in changed[0].payload  # never the text in an event
    assert changed[0].audience == ["all"]


def test_agents_read_a_humans_text_other_humans_do_not_and_the_switch_turns_it_off(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    agent = flow.agent(make_client, owner)
    other = second_human(make_client, migrated)
    put(owner, "Short answers.")
    path = f"/projects/maity/members/{owner.id}/preferences"
    assert agent.get(path).json()["markdown"] == "Short answers."
    assert owner.get(path).status_code == 200  # its own
    assert other.get(path).status_code == 404  # other humans do not read them
    assert agent.get(f"/projects/maity/members/{agent.id}/preferences").status_code == 404
    off = owner.client.put(
        "/api/v1/me/preferences/projects/maity",
        json={"include": False},
        headers={"X-CSRF-Token": owner.csrf},
    )
    assert off.status_code == 200, off.text
    assert off.json()["projects"] == [{"slug": "maity", "include": False}]
    assert agent.get(path).status_code == 404
    switched = events(migrated, "preferences_changed")[-1]
    assert switched.payload == {"human_id": owner.id, "included": False}


# --- proposals ------------------------------------------------------------------------------------


def propose(agent: flow.Agent, human_id: str, text: str, base: int = 0) -> Any:
    return agent.post(
        f"/projects/maity/members/{human_id}/preferences/proposals",
        {"markdown": text, "base_version": base, "reason": "from what I saw today"},
    )


def answer(human: flow.Human, request_id: str, **body: Any) -> Any:
    return human.post(f"/requests/{request_id}/answer", body)


def test_only_an_admin_agent_or_the_proxy_proposes(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    member = flow.agent(make_client, owner)
    admin = flow.agent(make_client, owner, role="admin")
    refused = propose(member, owner.id, "Be brief.")
    assert refused.status_code == 403
    assert refused.json()["error"]["details"]["reason"] == "may_not_propose"
    assert propose(admin, "hum-nobody", "Be brief.").status_code == 404
    proposed = propose(admin, owner.id, "Be brief.")
    assert proposed.status_code == 202, proposed.text
    request = proposed.json()
    assert request["personal"] is True and request["to"] == f"human:{owner.id}"
    # Not in the project's list, in the human's personal inbox.
    assert owner.get("/projects/maity/requests?to=all").json()["items"] == []
    inbox = owner.get("/requests").json()["items"]
    assert [r["id"] for r in inbox] == [request["id"]]


def test_a_new_proposal_supersedes_the_open_one_and_five_a_day_is_the_cap(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    admin = flow.agent(make_client, owner, role="admin")
    ids = [propose(admin, owner.id, f"version {n}").json()["id"] for n in range(5)]
    statuses = {r["id"]: r["status"] for r in owner.get("/requests?status=all").json()["items"]}
    assert [statuses[i] for i in ids] == ["withdrawn"] * 4 + ["open"]
    assert propose(admin, owner.id, "one more").status_code == 429


def test_the_review_go_edited_go_no_and_a_stale_go(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    admin = flow.agent(make_client, owner, role="admin")
    first = propose(admin, owner.id, "Be brief.").json()
    shown = owner.get(f"/requests/{first['id']}").json()["memory_proposal"]
    assert shown["current"] == {"markdown": "", "version": 0} and shown["stale"] is False
    assert answer(owner, first["id"], reply_id="go").status_code == 200
    current = owner.get("/me/preferences").json()
    assert current["version"] == 1 and current["markdown"] == "Be brief."
    assert current["by"]["kind"] == "agent" and current["confirmed_by"] == owner.id
    assert current["proposed_by"]["request_id"] == first["id"]
    assert current["proposed_by"]["project"] == "maity"

    second = propose(admin, owner.id, "Be very brief.", base=1).json()
    edited = answer(owner, second["id"], reply_id="go", markdown="Be brief, kind.", base_version=1)
    assert edited.status_code == 200, edited.text
    now = owner.get("/me/preferences").json()
    assert (now["version"], now["markdown"], now["by"]["kind"], now["confirmed_by"]) == (
        2,
        "Be brief, kind.",
        "human",
        None,
    )
    assert owner.get(f"/requests/{second['id']}").json()["memory_proposal"]["result"] == {
        "version": 2,
        "edited": True,
    }

    third = propose(admin, owner.id, "Shout.", base=1).json()  # made on version 1
    stale = answer(owner, third["id"], reply_id="go")
    assert stale.status_code == 409
    assert stale.json()["error"]["details"] == {"current_version": 2, "base_version": 1}
    assert owner.get(f"/requests/{third['id']}").json()["status"] == "open"
    assert owner.get(f"/requests/{third['id']}").json()["memory_proposal"]["stale"] is True
    assert answer(owner, third["id"], reply_id="no", text="not like that").status_code == 200
    assert owner.get("/me/preferences").json()["version"] == 2


def test_an_edit_belongs_only_to_a_preference_proposals_go(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    admin = flow.agent(make_client, owner, role="admin")
    request = propose(admin, owner.id, "Be brief.").json()
    without_base = answer(owner, request["id"], reply_id="go", markdown="x")
    assert without_base.json()["error"]["details"]["fields"] == {
        "markdown": "go_with_markdown_and_base_version"
    }


# --- the resume packet --------------------------------------------------------------------------


def write_for(engine: Engine, human_id: str, text: str) -> None:
    with transaction(engine) as conn:
        preferences.write(
            conn,
            human_id,
            text,
            by=("human", human_id),
            proposed_by=None,
            confirmed_by=None,
            base_version=None,
        )


def test_the_packet_quotes_the_humans_owner_first_and_holds_at_most_eight(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    agent = flow.agent(make_client, owner)
    write_for(migrated, owner.id, "The owner's way.")
    for n in range(8):
        other = second_human(make_client, migrated, handle=f"aa-{n}")
        write_for(migrated, other.id, f"human {n}")
    block = agent.resume().json()["preferences"]
    assert block["notice"].startswith("How these humans like to work")
    assert len(block["items"]) == 8 and block["truncated"] is True
    assert block["items"][0]["human"] == {"id": owner.id, "handle": "maintainer"}
    assert [i["human"]["handle"] for i in block["items"][1:]] == [f"aa-{n}" for n in range(7)]


def test_an_agent_given_its_owners_text_gets_it_on_its_membership_owner_member_or_not(
    make_client: ClientFactory, migrated: Engine
) -> None:
    lead = flow.human(make_client, migrated)
    flow.project(lead)
    stranger = flow.human(make_client, migrated, handle="stranger")
    write_for(migrated, stranger.id, "The stranger's way.")
    # An agent of the project whose profile the stranger owns; the stranger is no member.
    agent = flow.agent(make_client, lead)
    with migrated.begin() as conn:
        conn.execute(
            t.agent_profile.update()
            .where(t.agent_profile.c.id == agent.id)
            .values(owner_id=stranger.id)
        )
    refused = agent.patch(f"/projects/maity/members/{agent.id}", {"owner_preferences": True})
    assert refused.status_code == 403
    assert refused.json()["error"]["details"]["reason"] == "humans_only"
    given = stranger.patch(f"/projects/maity/members/{agent.id}", {"owner_preferences": True})
    assert given.status_code == 204, given.text  # the owner is no member: no body
    packet = agent.resume().json()
    assert packet["membership"]["owner_preferences"]["markdown"] == "The stranger's way."
    assert [i["human"]["id"] for i in packet["preferences"]["items"]] == []
    assert agent.get(f"/projects/maity/members/{stranger.id}/preferences").status_code == 200
    stranger.patch(f"/projects/maity/members/{agent.id}", {"owner_preferences": False})
    assert agent.resume().json()["membership"]["owner_preferences"] is None


# --- the basis of a decision in the owner's stead ------------------------------------------------


def test_the_basis_names_the_deciding_agents_owner_and_a_version_that_exists(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    agent = flow.agent(make_client, owner)
    write_for(migrated, owner.id, "v1")
    with migrated.connect() as conn:

        def errors(basis: dict[str, Any]) -> dict[str, str]:
            return preferences.basis_errors(conn, agent.id, basis)

        assert errors({"human_id": owner.id, "preferences_version": 1}) == {}
        assert errors({"human_id": owner.id, "preferences_version": 0}) == {}
        assert errors({"human_id": owner.id, "preferences_version": 2}) == {
            "basis": "unknown_version"
        }
        assert errors({"human_id": "hum-other", "preferences_version": 1}) == {
            "basis": "not_owner_preferences"
        }


def test_the_humans_proxy_proposes_for_the_owner_only(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    proxy = flow.agent(make_client, owner, role="proxy")
    other = second_human(make_client, migrated)
    assert propose(proxy, owner.id, "Be brief.").status_code == 202
    refused = propose(proxy, other.id, "Be brief.")  # not the project's owner
    assert refused.json()["error"]["details"]["reason"] == "may_not_propose"
