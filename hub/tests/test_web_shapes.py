"""The shapes of the hub's answers that the dashboard's fixtures must follow.

The hub has no response models: its answers are dicts built by view functions. So the
fixtures are checked against shapes recorded here instead (web/tools/check.py compares
them): for each request of web/tools/shape-requests.json, the keys and the JSON type of
every value, never the values. A change to one of these answers fails this test until the
shapes are written again with one command, `make -C web shapes`, in the same pull request.
"""

from __future__ import annotations

import importlib.util
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import select

from maity_hub import tables as t
from maity_hub.access import membership
from maity_hub.auth.caller import Caller
from maity_hub.events import transaction
from maity_hub.routes.requests import file_personal
from tests import factory, flow
from tests.conftest import ClientFactory
from tests.test_runners import paired

WEB_TOOLS = Path(__file__).resolve().parents[2] / "web" / "tools"
SHAPES = WEB_TOOLS / "hub-shapes.json"


def shape(value: Any, maps: frozenset[str] = frozenset(), at: str = "") -> Any:
    """A value's form: "string", "number", "boolean", "null", {"object": {key: form}},
    {"array": form of every item merged, or null when empty}, or, at a path named in
    `maps` (keys that are data, as section numbers), {"map": form of every value merged}."""
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int | float):
        return "number"
    if isinstance(value, str):
        return "string"
    if value is None:
        return "null"
    merged: Any = None
    if isinstance(value, list):
        for item in value:
            merged = merge(merged, shape(item, maps, at + "[]"))
        return {"array": merged}
    if at in maps:
        for item in value.values():
            merged = merge(merged, shape(item, maps, at + "{}"))
        return {"map": merged}
    return {"object": {k: shape(v, maps, f"{at}.{k}") for k, v in sorted(value.items())}}


def merge(a: Any, b: Any) -> Any:
    """Two forms of the same place as one: keys united, a null beside a type gives the type."""
    if a is None or (a == "null" and b is not None):
        return b
    if b is None or b == "null" or a == b:
        return a
    if isinstance(a, dict) and isinstance(b, dict) and a.keys() == b.keys():
        (kind,) = a.keys()
        if kind == "object":
            keys = a["object"].keys() | b["object"].keys()
            return {
                "object": {k: merge(a["object"].get(k), b["object"].get(k)) for k in sorted(keys)}
            }
        if kind != "any":
            return {kind: merge(a[kind], b[kind])}
    return {"any": sorted({json.dumps(a, sort_keys=True), json.dumps(b, sort_keys=True)})}


def test_web_check_computes_the_same_forms() -> None:
    """web/tools/check.py has its own copy of shape() and merge() (the web tools use the
    standard library only); the two must give the same form for the same value."""
    spec = importlib.util.spec_from_file_location("web_check", WEB_TOOLS / "check.py")
    assert spec and spec.loader
    check = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(check)
    maps = frozenset({".m", ".m{}"})
    values: list[Any] = [
        None,
        True,
        3,
        2.5,
        "x",
        [],
        [1, None, 2],
        [1, "x"],
        [{"a": 1}, {"b": None}, {"a": None, "b": "y"}],
        {"m": {"1": [1], "2": [], "3": None}, "n": {"1": True}},
        {"m": {"1": None, "2": ["x"]}},
        {"m": {"a": {"x": 1}, "b": {"y": "z"}}},
        [[{"a": 1}], [], [{"a": "z"}]],
    ]
    for value in values:
        assert check.shape_of(value, maps) == shape(value, maps), value
    for a in values:
        for b in values:
            assert check.merge_shapes(shape(a, maps), shape(b, maps)) == merge(
                shape(a, maps), shape(b, maps)
            ), (a, b)


def _ok(answer: Any) -> Any:
    assert answer.status_code < 300, answer.text
    return answer.json()


def _personal_from_elsewhere(make_client: ClientFactory, engine: Any, owner: flow.Human) -> None:
    """The owner's agent in another human's project, where the owner is no member, asks
    the owner personally (§7): only that notification carries `project.member`."""
    friend = flow.human(make_client, engine, "friend")
    lab = flow.project(friend, "lab")
    lent = factory.agent(engine, lab["id"], owner.id).agent_id
    with transaction(engine) as conn:
        row = conn.execute(select(t.membership).where(t.membership.c.agent_id == lent)).one()
        caller = Caller(
            kind="agent",
            via="bearer",
            agent_id=lent,
            membership_id=row.id,
            project_id=row.project_id,
        )
        mine = membership(conn, caller, "friend/lab")
        file_personal(conn, mine, caller, lent, "consent", "May I?", "the text")


def _seed(make_client: ClientFactory, migrated: Any) -> tuple[flow.Human, dict[str, str]]:
    """A project with something in every list the recorded answers carry, so a list's
    items are compared too: an empty list says nothing about their form."""
    owner = flow.human(make_client, migrated)
    flow.project(owner, repository={"url": "https://github.com/maintainer/maity"})
    agent = flow.agent(make_client, owner, agent={"handle": "agent-a", "display_name": "Agent A"})
    other = flow.agent(make_client, owner)
    base = "/projects/maintainer/maity"
    # settings.ticker is only in the answer once set (§17.3), as in the fixture project.
    ticker = {
        "enabled": True,
        "contract_files": ["context/contract.md"],
        "contract_implementers": {"*": ["role:coder"]},
    }
    _ok(owner.patch(base, {"settings": {"ticker": ticker, "release_checklist": ["Tests"]}}))
    _ok(owner.post(f"{base}/conversations/{agent.id}/messages", {"body": "Hello @agent-a"}))
    group = _ok(
        owner.post(f"{base}/conversations", {"title": "Go", "participants": [agent.id, other.id]})
    )
    _ok(owner.post(f"{base}/conversations/{group['id']}/messages", {"body": "Go? @agent-a"}))
    first = _ok(owner.post(f"{base}/tasks", {"title": "A card", "body": "For @agent-a."}))
    note = _ok(owner.post(f"{base}/tasks/{first['id']}/notes", {"body": "A note for @agent-a."}))
    edit = {"body": "A note for @agent-a, edited.", "reason": "typo", "base_version": 1}
    _ok(owner.patch(f"{base}/tasks/{first['id']}/notes/{note['id']}", edit))
    _ok(
        owner.post(
            f"{base}/tasks/{first['id']}/links",
            {"kind": "issue", "forge_url": "https://github.com/maintainer/maity/issues/1"},
        )
    )
    second = {"title": "Next", "depends_on": [first["id"]], "related": [first["id"]]}
    _ok(owner.post(f"{base}/tasks", second | {"ships_with": [first["id"]]}))
    options = [{"id": "yes", "label": "Yes"}, {"id": "no", "label": "No"}]
    _ok(agent.post(f"{base}/requests", {"class": "decision", "title": "Ship?", "options": options}))
    _personal_from_elsewhere(make_client, migrated, owner)
    runner = paired(make_client, owner)
    # `maintenance` in `GET /me` is an object only while a window is announced (§16.12).
    starts = datetime.now(UTC).replace(microsecond=0) + timedelta(days=1)
    window = {
        "from": starts.isoformat().replace("+00:00", "Z"),
        "until": (starts + timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
        "text": "Upgrade",
    }
    _ok(
        owner.client.put(
            "/api/v1/admin/maintenance", json=window, headers={"X-CSRF-Token": owner.csrf}
        )
    )
    ids = {
        "project": "maintainer/maity",
        "agent": agent.id,
        "group": group["id"],
        "task": first["id"],
        "runner": runner.id,
    }
    return owner, ids


def test_the_recorded_shapes_are_the_hubs(make_client: ClientFactory, migrated: Any) -> None:
    spec = json.loads((WEB_TOOLS / "shape-requests.json").read_text())
    owner, ids = _seed(make_client, migrated)
    maps = frozenset(spec["maps"])
    recorded = {}
    for request in spec["requests"]:
        path = request["path"].format(**ids)
        call = owner.delete if request["method"] == "DELETE" else owner.get
        answer = call(path)
        assert answer.status_code < 300, (path, answer.status_code, answer.text)
        recorded[f'{request["method"]} {request["path"]}'] = shape(answer.json(), maps)
    text = json.dumps(recorded, indent=1, sort_keys=True) + "\n"
    if os.environ.get("MAITY_WRITE_SHAPES"):
        SHAPES.write_text(text)
    stale = "the hub's answers changed shape: run `make -C web shapes`, commit hub-shapes.json"
    assert SHAPES.exists() and SHAPES.read_text() == text, stale
