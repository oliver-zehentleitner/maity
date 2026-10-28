"""docs/api.md §6.7 and §6.8: release cards and their readiness, contract cards."""

from __future__ import annotations

import json
from dataclasses import replace
from typing import Any

import pytest
from sqlalchemy import Engine, delete, insert, select, update

from maity_hub import clock
from maity_hub import tables as t
from maity_hub.config import Settings
from maity_hub.probe import Worker
from maity_hub.routes import tasks as tasks_routes
from tests import flow
from tests.conftest import ClientFactory

REPO = {"url": "https://github.com/acme/maity", "default_branch": "main"}
SHA = "d91e294c" + "0" * 32
OTHER_SHA = "e" * 40
RELEASE_KEYS = {
    "version",
    "pull_requests",
    "pull_requests_typed",
    "groups",
    "checklist",
    "readiness",
    "tag",
}


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    owner = flow.human(make_client, migrated)
    flow.project(owner, "maity", repository=REPO)
    checklist = ["CHANGELOG has a section", "live version equals the tag"]
    response = owner.patch(
        "/projects/maintainer/maity", {"settings": {"release_checklist": checklist}}
    )
    assert response.status_code == 200, response.text
    return owner


@pytest.fixture
def settings(settings: Settings, request: pytest.FixtureRequest) -> Settings:
    """The operator's forge token, as the environment sets it, for the tests that
    ask for the probe; the others run without one."""
    if {"probe", "github"} & set(request.fixturenames):
        return replace(settings, forge_github_token="test-token")
    return settings


@pytest.fixture
def probe(monkeypatch: pytest.MonkeyPatch) -> None:
    """A forge token as the operator would set it (`settings` below); observations are
    inserted by hand, so the worker never starts."""
    monkeypatch.setattr(Worker, "start", lambda self: None)


def task(who: Any, **body: Any) -> dict[str, Any]:
    response = who.post("/projects/maintainer/maity/tasks", {"title": "A card", **body})
    assert response.status_code == 201, response.text
    result: dict[str, Any] = response.json()
    return result


def release(who: Any, version: str = "0.1.0", **body: Any) -> dict[str, Any]:
    return task(who, kind="release", release={"version": version}, **body)


def _get(who: Any, card: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = who.get(f"/projects/maintainer/maity/tasks/{card['id']}").json()
    return result


def _set(engine: Engine, card: dict[str, Any], **values: Any) -> None:
    with engine.begin() as conn:
        conn.execute(update(t.card).where(t.card.c.id == card["id"]).values(**values))


def _reported(engine: Engine, card: dict[str, Any], number: int, head: str = SHA) -> None:
    pr = {"number": number, "url": f"https://github.com/acme/maity/pull/{number}", "head": head}
    _set(engine, card, report={"pr": pr, "pr_status": "found"})


def _observe(engine: Engine, number: int, state: str = "merged", head: str = SHA) -> None:
    data = {"found": True, "state": state, "checks": "success", "head_sha": head, "merged_at": None}
    with engine.begin() as conn:
        project_id = conn.execute(select(t.project.c.id)).scalar()
        conn.execute(
            insert(t.forge_observation).values(
                project_id=project_id,
                kind="pr",
                ref=str(number),
                observed_at=clock.now(),
                data=data,
            )
        )


def _blocking(who: Any, card: dict[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = _get(who, card)["release"]["readiness"]["blocking"]
    return result


def _unordered(items: list[dict[str, Any]]) -> list[str]:
    """§6.7 gives `blocking` no order."""
    return sorted(json.dumps(item, sort_keys=True) for item in items)


def _events(engine: Engine, kind: str) -> list[Any]:
    with engine.connect() as conn:
        return list(conn.execute(select(t.event).where(t.event.c.kind == kind)).all())


# --- releases (§6.7) ----------------------------------------------------------------------


def test_a_release_card_has_the_contract_shape(owner: flow.Human) -> None:
    card = release(owner)
    assert card["id"].startswith("rel-") and card["kind"] == "release"
    assert set(card["release"]) == RELEASE_KEYS and card["contract"] is None
    assert card["release"]["version"] == "0.1.0" and card["release"]["tag"] is None
    assert [(i["id"], i["text"], i["done"]) for i in card["release"]["checklist"]] == [
        ("chk-1", "CHANGELOG has a section", False),
        ("chk-2", "live version equals the tag", False),
    ]
    assert card["release"]["readiness"] == {
        "ready": False,
        "blocking": [{"reason": "probe_not_configured"}],
    }
    assert task(owner)["release"] is None


@pytest.mark.parametrize(
    "version", ["1.0", "01.0.0", "1.0.0+build", "v1.0.0", "1.0.0-", "1\u0660.0.0", "0.0.1-\u0661a"]
)
def test_a_version_is_semver(owner: flow.Human, version: str) -> None:
    response = owner.post(
        "/projects/maintainer/maity/tasks",
        {"title": "x", "kind": "release", "release": {"version": version}},
    )
    assert response.json()["error"]["details"]["fields"] == {"release.version": "not_semver"}


def test_one_release_in_flight_and_each_version_once(owner: flow.Human) -> None:
    first = release(owner, "1.0.0-rc.1")
    busy = owner.post(
        "/projects/maintainer/maity/tasks",
        {"title": "x", "kind": "release", "release": {"version": "1.0.0"}},
    )
    assert busy.status_code == 409
    assert busy.json()["error"]["code"] == "release_in_flight"
    assert busy.json()["error"]["details"] == {"release": first["id"]}
    cancelled = owner.patch(
        f"/projects/maintainer/maity/tasks/{first['id']}", {"status": "cancelled"}
    )
    assert cancelled.status_code == 200, cancelled.text
    again = owner.post(
        "/projects/maintainer/maity/tasks",
        {"title": "x", "kind": "release", "release": {"version": "1.0.0-rc.1"}},
    )
    assert (again.status_code, again.json()["error"]["code"]) == (409, "version_exists")
    assert release(owner, "1.0.0")["release"]["version"] == "1.0.0"


def test_a_release_needs_releases_write(owner: flow.Human, make_client: ClientFactory) -> None:
    agent = flow.agent(make_client, owner)  # role member
    response = agent.post(
        "/projects/maintainer/maity/tasks",
        {"title": "x", "kind": "release", "release": {"version": "1.0.0"}},
    )
    assert response.status_code == 403
    assert response.json()["error"]["details"]["scope"] == "releases:write"


def test_without_a_probe_a_release_is_never_done(owner: flow.Human, migrated: Engine) -> None:
    card = release(owner)
    _set(migrated, card, status="review")
    refused = owner.patch(f"/projects/maintainer/maity/tasks/{card['id']}", {"status": "done"})
    assert (refused.status_code, refused.json()["error"]["code"]) == (409, "release_not_ready")
    assert refused.json()["error"]["details"] == {"blocking": [{"reason": "probe_not_configured"}]}


def test_readiness_comes_from_observed_state_only(
    owner: flow.Human, migrated: Engine, probe: None
) -> None:
    shipped = task(owner)
    _reported(migrated, shipped, 7)
    card = release(owner, depends_on=[shipped["id"]])
    patched = owner.patch(
        f"/projects/maintainer/maity/tasks/{card['id']}",
        {"release": {"pull_requests_typed": [{"number": 1, "state": "merged"}]}},
    )
    assert patched.status_code == 200, patched.text
    view = patched.json()["release"]
    assert [
        (p["number"], p["source"], p["task_id"], p["state"]) for p in view["pull_requests"]
    ] == [
        (1, "typed", None, "merged"),  # attested, not observed: counts for nothing
        (7, "reported", shipped["id"], None),
    ]
    assert _unordered(view["readiness"]["blocking"]) == _unordered(
        [
            {"reason": "task_open", "task": shipped["id"]},
            {"reason": "pr_unverified", "pr": 1},
            {"reason": "pr_unverified", "pr": 7},
            {"reason": "checklist_open", "item": "chk-1"},
            {"reason": "checklist_open", "item": "chk-2"},
        ]
    )
    _observe(migrated, 1)
    _observe(migrated, 7, state="open", head="e" * 40)
    blocking = _blocking(owner, card)
    assert {"reason": "pr_open", "pr": 7} in blocking
    assert {"reason": "pr_mismatch", "pr": 7} in blocking
    assert not [b for b in blocking if b.get("pr") == 1]
    entry = _get(owner, card)["release"]["pull_requests"][1]
    assert (entry["state"], entry["head_sha"], entry["checks"]) == ("open", "e" * 40, "success")
    assert entry["observed_at"] is not None


def test_release_ready_is_announced_once_and_done_frees_the_slot(
    owner: flow.Human, migrated: Engine, probe: None
) -> None:
    shipped = task(owner)
    _reported(migrated, shipped, 7)
    _observe(migrated, 7)
    card = release(owner, depends_on=[shipped["id"]])
    _set(migrated, shipped, status="review")
    done = owner.patch(f"/projects/maintainer/maity/tasks/{shipped['id']}", {"status": "done"})
    assert done.status_code == 200, done.text
    for item in ("chk-1", "chk-2"):
        ticked = owner.post(
            f"/projects/maintainer/maity/tasks/{card['id']}/checklist/{item}", {"done": True}
        )
        assert ticked.status_code == 200, ticked.text
    view = _get(owner, card)["release"]
    assert view["readiness"] == {"ready": True, "blocking": []}
    assert view["checklist"][0]["by"] == owner.id and view["checklist"][0]["at"] is not None
    announced = _events(migrated, "release_ready")
    assert len(announced) == 1
    assert announced[0].audience == ["all"]
    assert announced[0].payload == {"release": card["id"], "version": "0.1.0"}
    # Unchanged readiness announces nothing more.
    owner.patch(f"/projects/maintainer/maity/tasks/{card['id']}", {"title": "0.1.0 — first build"})
    assert len(_events(migrated, "release_ready")) == 1
    _set(migrated, card, status="review")
    closed = owner.patch(f"/projects/maintainer/maity/tasks/{card['id']}", {"status": "done"})
    assert closed.status_code == 200, closed.text
    assert release(owner, "0.2.0")["status"] == "open"


def test_ready_is_announced_again_after_a_turn_back(
    owner: flow.Human, migrated: Engine, probe: None
) -> None:
    card = release(owner)
    tick = f"/projects/maintainer/maity/tasks/{card['id']}/checklist"
    owner.post(f"{tick}/chk-1", {"done": True})
    owner.post(f"{tick}/chk-2", {"done": True})
    owner.post(f"{tick}/chk-2", {"done": False})
    assert _blocking(owner, card) == [{"reason": "checklist_open", "item": "chk-2"}]
    item = _get(owner, card)["release"]["checklist"][1]
    assert (item["by"], item["at"]) == (None, None)
    owner.post(f"{tick}/chk-2", {"done": True})
    assert len(_events(migrated, "release_ready")) == 2


def test_a_ships_with_group_is_complete_when_all_its_prs_are_merged(
    owner: flow.Human, migrated: Engine, probe: None
) -> None:
    first = task(owner)
    second = task(owner, ships_with=[first["id"]])
    _reported(migrated, first, 3)
    _reported(migrated, second, 4)
    card = release(owner, depends_on=[first["id"], second["id"]])
    group = sorted([first["id"], second["id"]])
    assert _get(owner, card)["release"]["groups"] == [group]
    _observe(migrated, 3)
    blocking = _blocking(owner, card)
    assert {"reason": "group_incomplete", "tasks": group} in blocking
    _observe(migrated, 4)
    assert {"reason": "group_incomplete", "tasks": group} not in _blocking(owner, card)


def test_the_checklist_is_edited_with_patch(owner: flow.Human, migrated: Engine) -> None:
    card = release(owner)
    owner.post(f"/projects/maintainer/maity/tasks/{card['id']}/checklist/chk-2", {"done": True})
    patched = owner.patch(
        f"/projects/maintainer/maity/tasks/{card['id']}",
        {"release": {"checklist": [{"id": "chk-2", "text": "tag is live"}, {"text": "notes"}]}},
    )
    assert patched.status_code == 200, patched.text
    checklist = patched.json()["release"]["checklist"]
    assert [(i["id"], i["text"], i["done"]) for i in checklist] == [
        ("chk-2", "tag is live", True),
        ("chk-3", "notes", False),
    ]
    unknown = owner.patch(
        f"/projects/maintainer/maity/tasks/{card['id']}",
        {"release": {"checklist": [{"id": "chk-9", "text": "x"}]}},
    )
    assert unknown.json()["error"]["details"]["fields"] == {
        "release.checklist": "unknown_item:chk-9"
    }
    missing = owner.post(
        f"/projects/maintainer/maity/tasks/{card['id']}/checklist/chk-1", {"done": True}
    )
    assert missing.status_code == 404


def test_only_a_releaser_or_the_holder_ticks(owner: flow.Human, make_client: ClientFactory) -> None:
    agent = flow.agent(make_client, owner)
    card = release(owner)
    path = f"/projects/maintainer/maity/tasks/{card['id']}/checklist/chk-1"
    refused = agent.post(path, {"done": True})
    assert refused.status_code == 403
    assert agent.post(f"/projects/maintainer/maity/tasks/{card['id']}/claim", {}).status_code == 200
    assert agent.post(path, {"done": True}).status_code == 200
    plain = task(owner)
    path = f"/projects/maintainer/maity/tasks/{plain['id']}/checklist/chk-1"
    assert owner.post(path, {"done": True}).status_code == 404


# --- contract cards (§6.8) ----------------------------------------------------------------


def test_a_contract_card_defaults_its_arbiter_and_checks_watchers(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    agent = flow.agent(make_client, owner)
    card = task(owner, kind="contract", contract={"watchers": [agent.id, agent.id]})
    assert card["id"].startswith("ctr-") and card["release"] is None
    assert card["contract"] == {
        "arbiter": "role:admin",
        "state": "proposed",
        "watchers": [agent.id],
        "path": "docs/api.md",
        "section": None,
    }
    stranger = owner.post(
        "/projects/maintainer/maity/tasks",
        {"title": "x", "kind": "contract", "contract": {"watchers": ["agt-nobody"]}},
    )
    assert stranger.json()["error"]["details"]["fields"] == {"contract.watchers": "not_a_member"}
    misplaced = owner.post("/projects/maintainer/maity/tasks", {"title": "x", "contract": {}})
    assert misplaced.json()["error"]["details"]["fields"] == {"contract": "contracts_only"}


def test_only_the_arbiter_finalises_and_the_watchers_hear(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    arbiter = flow.agent(make_client, owner)
    watcher = flow.agent(make_client, owner)
    other = flow.agent(make_client, owner)
    # Naming an arbiter other than the policy's is an admin's call.
    named = {"arbiter": arbiter.id, "watchers": [watcher.id]}
    self_named = other.post(
        "/projects/maintainer/maity/tasks",
        {"title": "x", "kind": "contract", "contract": {"arbiter": other.id}},
    )
    assert (self_named.status_code, self_named.json()["error"]["details"]["scope"]) == (
        403,
        "tasks:admin",
    )
    assert task(other, kind="contract")["contract"]["arbiter"] == "role:admin"
    card = task(owner, kind="contract", contract=named)
    path = f"/projects/maintainer/maity/tasks/{card['id']}"
    refused = other.patch(path, {"contract": {"state": "final"}})
    assert refused.status_code == 403
    final = arbiter.patch(path, {"contract": {"state": "final"}})
    assert final.status_code == 200, final.text
    assert final.json()["contract"]["state"] == "final"
    with migrated.connect() as conn:
        event = conn.execute(
            select(t.event).where(t.event.c.kind == "task_updated").order_by(t.event.c.seq.desc())
        ).first()
    assert event is not None and f"member:{watcher.id}" in event.audience
    assert event.payload["contract"]["state"] == "final"
    # An admin may finalise too; the owner holds tasks:admin.
    second = task(owner, kind="contract", contract={"arbiter": arbiter.id})
    assert (
        owner.patch(
            f"/projects/maintainer/maity/tasks/{second['id']}", {"contract": {"state": "final"}}
        ).json()["contract"]["state"]
        == "final"
    )


def _empty_checklist(owner: flow.Human) -> None:
    response = owner.patch("/projects/maintainer/maity", {"settings": {"release_checklist": []}})
    assert response.status_code == 200, response.text


def test_a_partner_outside_the_release_blocks_its_group(
    owner: flow.Human, migrated: Engine, probe: None
) -> None:
    _empty_checklist(owner)
    first = task(owner)
    second = task(owner, ships_with=[first["id"]])
    _reported(migrated, first, 3)
    _reported(migrated, second, 4)
    _observe(migrated, 3)
    _observe(migrated, 4, state="open")
    _set(migrated, first, status="done")
    card = release(owner, depends_on=[first["id"]])
    group = sorted([first["id"], second["id"]])
    view = _get(owner, card)["release"]
    assert view["groups"] == [group]
    assert view["readiness"]["blocking"] == [{"reason": "group_incomplete", "tasks": group}]
    _set(migrated, card, status="review")
    refused = owner.patch(f"/projects/maintainer/maity/tasks/{card['id']}", {"status": "done"})
    assert refused.json()["error"]["code"] == "release_not_ready"
    assert _events(migrated, "release_ready") == []


def test_done_is_judged_on_the_data_as_it_will_be_stored(
    owner: flow.Human, migrated: Engine, probe: None
) -> None:
    _empty_checklist(owner)
    card = release(owner)
    assert _get(owner, card)["release"]["readiness"]["ready"] is True
    _set(migrated, card, status="review")
    path = f"/projects/maintainer/maity/tasks/{card['id']}"
    for change in (
        {"checklist": [{"text": "one more thing"}]},
        {"pull_requests_typed": [{"number": 99, "state": "merged"}]},
    ):
        refused = owner.patch(path, {"status": "done", "release": change})
        assert refused.json()["error"]["code"] == "release_not_ready", change
    assert _get(owner, card)["status"] == "review"


def test_a_ready_release_is_announced_at_creation(
    owner: flow.Human, migrated: Engine, probe: None
) -> None:
    _empty_checklist(owner)
    card = release(owner)
    [announced] = _events(migrated, "release_ready")
    assert announced.payload == {"release": card["id"], "version": "0.1.0"}


def test_a_closed_release_is_the_record_of_what_shipped(owner: flow.Human) -> None:
    card = release(owner)
    shipped = task(owner)
    owner.patch(f"/projects/maintainer/maity/tasks/{card['id']}", {"status": "cancelled"})
    path = f"/projects/maintainer/maity/tasks/{card['id']}"
    changes: list[dict[str, Any]] = [
        {"release": {"checklist": []}},
        {"release": {"pull_requests_typed": [{"number": 1}]}},
        {"depends_on": [shipped["id"]]},
    ]
    for change in changes:
        response = owner.patch(path, change)
        assert response.json()["error"]["code"] == "invalid_transition", change


def test_a_releaser_edits_a_release_it_does_not_hold(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    reviewer = flow.agent(make_client, owner, role="reviewer")
    card = release(owner)
    path = f"/projects/maintainer/maity/tasks/{card['id']}"
    edited = reviewer.patch(path, {"release": {"pull_requests_typed": [{"number": 2}]}})
    assert edited.status_code == 200, edited.text
    assert reviewer.patch(path, {"title": "renamed"}).status_code == 403  # only release fields


def test_an_observation_replaces_the_attested_state(
    owner: flow.Human, migrated: Engine, probe: None
) -> None:
    card = release(owner)
    owner.patch(
        f"/projects/maintainer/maity/tasks/{card['id']}",
        {"release": {"pull_requests_typed": [{"number": 5, "state": "merged"}]}},
    )
    with migrated.begin() as conn:  # the forge has the PR but said nothing about the state
        project_id = conn.execute(select(t.project.c.id)).scalar()
        conn.execute(
            insert(t.forge_observation).values(
                project_id=project_id,
                kind="pr",
                ref="5",
                observed_at=clock.now(),
                data={"found": True},
            )
        )
    entry = _get(owner, card)["release"]["pull_requests"][0]
    assert entry["state"] is None
    assert {"reason": "pr_open", "pr": 5} in _blocking(owner, card)


def test_heads_are_compared_whole_once_per_pr(
    owner: flow.Human, migrated: Engine, probe: None
) -> None:
    first, second = task(owner), task(owner)
    _reported(migrated, first, 7, head=SHA)
    _reported(migrated, second, 7, head=OTHER_SHA)
    _observe(migrated, 7)
    card = release(owner, depends_on=[first["id"], second["id"]])
    mismatches = [b for b in _blocking(owner, card) if b["reason"] == "pr_mismatch"]
    assert mismatches == [{"reason": "pr_mismatch", "pr": 7}]
    _reported(migrated, second, 7, head=SHA)
    assert not [b for b in _blocking(owner, card) if b["reason"] == "pr_mismatch"]


def test_a_removed_checklist_id_is_never_given_out_again(owner: flow.Human) -> None:
    card = release(owner)
    path = f"/projects/maintainer/maity/tasks/{card['id']}"
    owner.patch(path, {"release": {"checklist": [{"id": "chk-1", "text": "keep"}]}})
    added = owner.patch(
        path, {"release": {"checklist": [{"id": "chk-1", "text": "keep"}, {"text": "new"}]}}
    )
    assert [i["id"] for i in added.json()["release"]["checklist"]] == ["chk-1", "chk-3"]


# --- the close, the frozen record ---------------------------------------------------------


def test_a_release_made_ready_by_its_closing_patch_is_announced(
    owner: flow.Human, migrated: Engine, probe: None
) -> None:
    _empty_checklist(owner)
    card = release(owner)  # ready, and announced, at creation
    path = f"/projects/maintainer/maity/tasks/{card['id']}"
    owner.patch(path, {"release": {"pull_requests_typed": [{"number": 9}]}})  # unready again
    _set(migrated, card, status="review")
    done = owner.patch(path, {"status": "done", "release": {"pull_requests_typed": []}})
    assert done.status_code == 200, done.text
    announced = _events(migrated, "release_ready")
    assert len(announced) == 2
    assert announced[-1].payload == {"release": card["id"], "version": "0.1.0"}
    assert done.json()["release"]["readiness"] == {"ready": True, "blocking": []}
    closing = _events(migrated, "task_updated")[-1]
    assert closing.payload["status"] == "done"
    assert announced[-1].seq > closing.seq  # the write's own event first, release_ready last


def test_a_report_that_closes_a_ready_release_announces_it_and_frees_the_slot(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, probe: None
) -> None:
    _empty_checklist(owner)
    releaser = flow.agent(make_client, owner, role="admin")
    shipped = task(owner)
    _set(migrated, shipped, status="done")
    _reported(migrated, shipped, 11)
    card = release(owner, depends_on=[shipped["id"]])
    assert _blocking(owner, card) == [{"reason": "pr_unverified", "pr": 11}]
    assert (
        releaser.post(f"/projects/maintainer/maity/tasks/{card['id']}/claim", {}).status_code == 200
    )
    report = {
        "summary": "Released 0.1.0",
        "head": SHA,
        "branch": "main",
        "remote_head": SHA,
        "pr_status": "none",
        "done": True,
    }
    refused = releaser.post(f"/projects/maintainer/maity/tasks/{card['id']}/report", report)
    assert refused.json()["error"]["code"] == "release_not_ready"
    _observe(migrated, 11)  # observed without a recheck: ready, not yet announced
    assert _events(migrated, "release_ready") == []
    closed = releaser.post(f"/projects/maintainer/maity/tasks/{card['id']}/report", report)
    assert closed.status_code == 200, closed.text
    assert closed.json()["status"] == "done"
    [announced] = _events(migrated, "release_ready")
    assert announced.payload["release"] == card["id"]
    assert release(owner, "0.2.0")["release"]["version"] == "0.2.0"  # the slot is free


def test_a_closed_release_keeps_what_it_froze(
    owner: flow.Human, migrated: Engine, probe: None
) -> None:
    _empty_checklist(owner)
    shipped = task(owner)
    _set(migrated, shipped, status="done")
    _reported(migrated, shipped, 12)
    _observe(migrated, 12)
    card = release(owner, depends_on=[shipped["id"]])
    _set(migrated, card, status="review")
    done = owner.patch(f"/projects/maintainer/maity/tasks/{card['id']}", {"status": "done"})
    assert done.status_code == 200, done.text
    frozen = _get(owner, card)["release"]
    assert frozen["readiness"] == {"ready": True, "blocking": []}
    partner = task(owner, ships_with=[shipped["id"]])  # a later edge
    with migrated.begin() as conn:  # a later observation, as the probe would replace it
        conn.execute(delete(t.forge_observation).where(t.forge_observation.c.ref == "12"))
    _observe(migrated, 12, state="closed")
    assert _get(owner, partner)["ships_with"] == [shipped["id"]]
    after = _get(owner, card)["release"]
    assert {k: after[k] for k in ("pull_requests", "groups", "readiness")} == {
        k: frozen[k] for k in ("pull_requests", "groups", "readiness")
    }


def test_ships_with_never_names_a_release_card(owner: flow.Human) -> None:
    card = release(owner)
    other = task(owner)
    naming = owner.post(
        "/projects/maintainer/maity/tasks", {"title": "x", "ships_with": [card["id"]]}
    )
    assert naming.json()["error"]["details"]["fields"] == {"ships_with": "release_card"}
    own = owner.patch(
        f"/projects/maintainer/maity/tasks/{card['id']}", {"ships_with": [other["id"]]}
    )
    assert own.json()["error"]["details"]["fields"] == {"ships_with": "release_card"}
    owner.patch(f"/projects/maintainer/maity/tasks/{card['id']}", {"status": "cancelled"})
    closed = owner.patch(
        f"/projects/maintainer/maity/tasks/{card['id']}", {"ships_with": [other["id"]]}
    )
    assert closed.json()["error"]["details"]["fields"] == {"ships_with": "release_card"}


def test_a_repository_change_resets_and_reannounces_readiness(
    owner: flow.Human, migrated: Engine, probe: None
) -> None:
    _empty_checklist(owner)
    card = release(owner)
    assert len(_events(migrated, "release_ready")) == 1
    owner.patch("/projects/maintainer/maity", {"repository": None})
    assert _blocking(owner, card) == [{"reason": "probe_not_configured"}]
    owner.patch("/projects/maintainer/maity", {"repository": REPO})
    assert _get(owner, card)["release"]["readiness"]["ready"] is True
    assert len(_events(migrated, "release_ready")) == 2


def test_a_lost_race_on_the_constraints_is_still_a_409(
    owner: flow.Human, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The pre-checks skipped, as when two creations pass them at once: the unique
    constraints answer, and the error is mapped, on every engine."""

    def unchecked(_conn: Any, _mine: Any, body: Any) -> dict[str, Any]:
        data = {
            "version": body.version,
            "pull_requests_typed": [],
            "checklist": [],
            "next_item": 1,
            "ready_announced": False,
        }
        return {"release_version": body.version, "release_in_flight": True, "release_data": data}

    first = release(owner, "1.0.0")
    monkeypatch.setattr(tasks_routes, "_new_release", unchecked)
    in_flight = owner.post(
        "/projects/maintainer/maity/tasks",
        {"title": "x", "kind": "release", "release": {"version": "2.0.0"}},
    )
    assert in_flight.status_code == 409, in_flight.text
    assert in_flight.json()["error"]["code"] == "release_in_flight"
    owner.patch(f"/projects/maintainer/maity/tasks/{first['id']}", {"status": "cancelled"})
    taken = owner.post(
        "/projects/maintainer/maity/tasks",
        {"title": "x", "kind": "release", "release": {"version": "1.0.0"}},
    )
    assert taken.status_code == 409, taken.text
    assert taken.json()["error"]["code"] == "version_exists"


def test_a_pull_request_the_forge_does_not_have_blocks_as_not_found(
    owner: flow.Human, migrated: Engine, probe: None
) -> None:
    card = release(owner)
    path = f"/projects/maintainer/maity/tasks/{card['id']}"
    owner.patch(path, {"release": {"pull_requests_typed": [{"number": 77}]}})
    assert _get(owner, card)["release"]["pull_requests"][0]["found"] is None  # not yet observed
    with migrated.begin() as conn:
        conn.execute(
            insert(t.forge_observation).values(
                project_id=conn.execute(select(t.project.c.id)).scalar(),
                kind="pr",
                ref="77",
                observed_at=clock.now(),
                data={"number": 77, "found": False},
            )
        )
    entry = _get(owner, card)["release"]["pull_requests"][0]
    assert (entry["found"], entry["state"], entry["observed_at"] is not None) == (False, None, True)
    assert [b for b in _blocking(owner, card) if b.get("pr")] == [
        {"reason": "pr_not_found", "pr": 77}
    ]
