"""The shapes of the hub's answers that the dashboard's fixtures must follow.

The hub has no response models: its answers are dicts built by view functions. So the
fixtures are checked against shapes recorded here instead (web/tools/check.py compares
them): for each request of web/tools/shape-requests.json, the keys and the JSON type of
every value, never the values. A change to one of these answers fails this test until the
shapes are written again with one command, `make -C web shapes`, in the same pull request.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from tests import flow
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


def test_the_recorded_shapes_are_the_hubs(make_client: ClientFactory, migrated: Any) -> None:
    spec = json.loads((WEB_TOOLS / "shape-requests.json").read_text())
    owner = flow.human(make_client, migrated)
    flow.project(owner)
    agent = flow.agent(make_client, owner)
    other = flow.agent(make_client, owner)
    base = "/projects/maintainer/maity"
    # settings.ticker is only in the answer once set (§17.3), as in the fixture project.
    ticker = {
        "enabled": True,
        "contract_files": ["context/contract.md"],
        "contract_implementers": {"*": ["role:coder"]},
    }
    patched = owner.patch(base, {"settings": {"ticker": ticker}})
    assert patched.status_code == 200, patched.text
    sent = owner.post(f"{base}/conversations/{agent.id}/messages", {"body": "Hello"})
    assert sent.status_code == 201, sent.text
    group = owner.post(
        f"{base}/conversations", {"title": "Release", "participants": [agent.id, other.id]}
    )
    assert group.status_code == 201, group.text
    group_id = group.json()["id"]
    assert (
        owner.post(f"{base}/conversations/{group_id}/messages", {"body": "Go?"}).status_code == 201
    )
    task = owner.post(f"{base}/tasks", {"title": "A card", "body": "Its text."})
    assert task.status_code == 201, task.text
    runner = paired(make_client, owner)
    ids = {
        "project": "maintainer/maity",
        "agent": agent.id,
        "group": group_id,
        "task": task.json()["id"],
        "runner": runner.id,
    }
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
