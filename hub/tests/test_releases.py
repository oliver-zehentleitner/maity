"""docs/api.md §6.7 and §6.8: release cards and their readiness, contract cards."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import Engine, insert, select, update

from maity_hub import clock, forge
from maity_hub import tables as t
from tests import flow
from tests.conftest import ClientFactory

REPO = {"url": "https://github.com/acme/maity", "default_branch": "main"}
SHA = "d91e294c" + "0" * 32
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
    response = owner.patch("/projects/maity", {"settings": {"release_checklist": checklist}})
    assert response.status_code == 200, response.text
    return owner


@pytest.fixture
def probe(monkeypatch: pytest.MonkeyPatch) -> None:
    """A forge token as the operator would set it; observations are inserted by hand."""
    monkeypatch.setattr(forge, "_token", "test-token")
    monkeypatch.setattr(forge, "configure", lambda token: None)


def task(who: Any, **body: Any) -> dict[str, Any]:
    response = who.post("/projects/maity/tasks", {"title": "A card", **body})
    assert response.status_code == 201, response.text
    result: dict[str, Any] = response.json()
    return result


def release(who: Any, version: str = "0.1.0", **body: Any) -> dict[str, Any]:
    return task(who, kind="release", release={"version": version}, **body)


def _get(who: Any, card: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = who.get(f"/projects/maity/tasks/{card['id']}").json()
    return result


def _set(engine: Engine, card: dict[str, Any], **values: Any) -> None:
    with engine.begin() as conn:
        conn.execute(update(t.card).where(t.card.c.id == card["id"]).values(**values))


def _reported(engine: Engine, card: dict[str, Any], number: int, head: str = SHA) -> None:
    pr = {"number": number, "url": f"https://github.com/acme/maity/pull/{number}", "head": head}
    _set(engine, card, report={"pr": pr, "pr_status": "found"})


def _observe(engine: Engine, number: int, state: str = "merged", head: str = SHA) -> None:
    data = {"state": state, "checks": "success", "head_sha": head, "merged_at": None}
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


@pytest.mark.parametrize("version", ["1.0", "01.0.0", "1.0.0+build", "v1.0.0", "1.0.0-"])
def test_a_version_is_semver(owner: flow.Human, version: str) -> None:
    response = owner.post(
        "/projects/maity/tasks",
        {"title": "x", "kind": "release", "release": {"version": version}},
    )
    assert response.json()["error"]["details"]["fields"] == {"release.version": "not_semver"}


def test_one_release_in_flight_and_each_version_once(owner: flow.Human) -> None:
    first = release(owner, "1.0.0-rc.1")
    busy = owner.post(
        "/projects/maity/tasks", {"title": "x", "kind": "release", "release": {"version": "1.0.0"}}
    )
    assert busy.status_code == 409
    assert busy.json()["error"]["code"] == "release_in_flight"
    assert busy.json()["error"]["details"] == {"release": first["id"]}
    cancelled = owner.patch(f"/projects/maity/tasks/{first['id']}", {"status": "cancelled"})
    assert cancelled.status_code == 200, cancelled.text
    again = owner.post(
        "/projects/maity/tasks",
        {"title": "x", "kind": "release", "release": {"version": "1.0.0-rc.1"}},
    )
    assert (again.status_code, again.json()["error"]["code"]) == (409, "version_exists")
    assert release(owner, "1.0.0")["release"]["version"] == "1.0.0"


def test_a_release_needs_releases_write(owner: flow.Human, make_client: ClientFactory) -> None:
    agent = flow.agent(make_client, owner)  # role member
    response = agent.post(
        "/projects/maity/tasks", {"title": "x", "kind": "release", "release": {"version": "1.0.0"}}
    )
    assert response.status_code == 403
    assert response.json()["error"]["details"]["scope"] == "releases:write"


def test_without_a_probe_a_release_is_never_done(owner: flow.Human, migrated: Engine) -> None:
    card = release(owner)
    _set(migrated, card, status="review")
    refused = owner.patch(f"/projects/maity/tasks/{card['id']}", {"status": "done"})
    assert (refused.status_code, refused.json()["error"]["code"]) == (409, "release_not_ready")
    assert refused.json()["error"]["details"] == {"blocking": [{"reason": "probe_not_configured"}]}


def test_readiness_comes_from_observed_state_only(
    owner: flow.Human, migrated: Engine, probe: None
) -> None:
    shipped = task(owner)
    _reported(migrated, shipped, 7)
    card = release(owner, depends_on=[shipped["id"]])
    patched = owner.patch(
        f"/projects/maity/tasks/{card['id']}",
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
    assert view["readiness"]["blocking"] == [
        {"reason": "task_open", "task": shipped["id"]},
        {"reason": "pr_unverified", "pr": 1},
        {"reason": "pr_unverified", "pr": 7},
        {"reason": "checklist_open", "item": "chk-1"},
        {"reason": "checklist_open", "item": "chk-2"},
    ]
    _observe(migrated, 1)
    _observe(migrated, 7, state="open", head="e" * 40)
    assert _blocking(owner, card)[1:3] == [
        {"reason": "pr_open", "pr": 7},
        {"reason": "pr_mismatch", "pr": 7},
    ]
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
    done = owner.patch(f"/projects/maity/tasks/{shipped['id']}", {"status": "done"})
    assert done.status_code == 200, done.text
    for item in ("chk-1", "chk-2"):
        ticked = owner.post(f"/projects/maity/tasks/{card['id']}/checklist/{item}", {"done": True})
        assert ticked.status_code == 200, ticked.text
    view = _get(owner, card)["release"]
    assert view["readiness"] == {"ready": True, "blocking": []}
    assert view["checklist"][0]["by"] == owner.id and view["checklist"][0]["at"] is not None
    announced = _events(migrated, "release_ready")
    assert len(announced) == 1
    assert announced[0].audience == ["all"]
    assert announced[0].payload == {"release": card["id"], "version": "0.1.0"}
    # Unchanged readiness announces nothing more.
    owner.patch(f"/projects/maity/tasks/{card['id']}", {"title": "0.1.0 — first build"})
    assert len(_events(migrated, "release_ready")) == 1
    _set(migrated, card, status="review")
    closed = owner.patch(f"/projects/maity/tasks/{card['id']}", {"status": "done"})
    assert closed.status_code == 200, closed.text
    assert release(owner, "0.2.0")["status"] == "open"


def test_ready_is_announced_again_after_a_turn_back(
    owner: flow.Human, migrated: Engine, probe: None
) -> None:
    card = release(owner)
    tick = f"/projects/maity/tasks/{card['id']}/checklist"
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
    owner.post(f"/projects/maity/tasks/{card['id']}/checklist/chk-2", {"done": True})
    patched = owner.patch(
        f"/projects/maity/tasks/{card['id']}",
        {"release": {"checklist": [{"id": "chk-2", "text": "tag is live"}, {"text": "notes"}]}},
    )
    assert patched.status_code == 200, patched.text
    checklist = patched.json()["release"]["checklist"]
    assert [(i["id"], i["text"], i["done"]) for i in checklist] == [
        ("chk-2", "tag is live", True),
        ("chk-3", "notes", False),
    ]
    unknown = owner.patch(
        f"/projects/maity/tasks/{card['id']}",
        {"release": {"checklist": [{"id": "chk-9", "text": "x"}]}},
    )
    assert unknown.json()["error"]["details"]["fields"] == {
        "release.checklist": "unknown_item:chk-9"
    }
    missing = owner.post(f"/projects/maity/tasks/{card['id']}/checklist/chk-1", {"done": True})
    assert missing.status_code == 404


def test_only_a_releaser_or_the_holder_ticks(owner: flow.Human, make_client: ClientFactory) -> None:
    agent = flow.agent(make_client, owner)
    card = release(owner)
    path = f"/projects/maity/tasks/{card['id']}/checklist/chk-1"
    refused = agent.post(path, {"done": True})
    assert refused.status_code == 403
    assert agent.post(f"/projects/maity/tasks/{card['id']}/claim", {}).status_code == 200
    assert agent.post(path, {"done": True}).status_code == 200
    plain = task(owner)
    path = f"/projects/maity/tasks/{plain['id']}/checklist/chk-1"
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
    }
    stranger = owner.post(
        "/projects/maity/tasks",
        {"title": "x", "kind": "contract", "contract": {"watchers": ["agt-nobody"]}},
    )
    assert stranger.json()["error"]["details"]["fields"] == {"contract.watchers": "not_a_member"}
    misplaced = owner.post("/projects/maity/tasks", {"title": "x", "contract": {}})
    assert misplaced.json()["error"]["details"]["fields"] == {"contract": "contracts_only"}


def test_only_the_arbiter_finalises_and_the_watchers_hear(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    arbiter = flow.agent(make_client, owner)
    watcher = flow.agent(make_client, owner)
    other = flow.agent(make_client, owner)
    card = task(other, kind="contract", contract={"arbiter": arbiter.id, "watchers": [watcher.id]})
    path = f"/projects/maity/tasks/{card['id']}"
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
            f"/projects/maity/tasks/{second['id']}", {"contract": {"state": "final"}}
        ).json()["contract"]["state"]
        == "final"
    )
