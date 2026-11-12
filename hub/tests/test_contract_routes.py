"""docs/api.md §12: the endpoint index and the hub's API routes name the same endpoints."""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

import pytest

CONTRACT = Path(__file__).parents[2] / "docs" / "api.md"
METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE")

# In the index without a route of the API, each for a reason. Remove an entry when its route
# comes: the test fails on an entry that no longer applies. One entry per line, sorted by method
# and path, its reason on the same line: a pull request adding or removing an entry touches only
# its own line, so parallel ones conflict here only when they change neighbouring lines.
NOT_ROUTED = {
    ("DELETE", "/projects/{}/{}/tasks/{}/objection-hold"),  # no route yet: tsk-4xqfxezvz0dh
    ("DELETE", "/runner/placements/{}/handover"),  # no route yet: tsk-j9e0yapj21wj
    ("GET", "/agents/{}/usage"),  # no route yet: tsk-m6sq1g0xwwn5, usage
    ("GET", "/me/briefings"),  # no route yet: tsk-k0k3jzrkpza2, briefings
    ("GET", "/me/briefings/versions"),  # no route yet: tsk-k0k3jzrkpza2, briefings
    ("GET", "/me/soul/versions"),  # no route yet: tsk-k0k3jzrkpza2, the agent's soul
    ("GET", "/openapi.json"),  # the machine form describes the routes, not itself
    ("GET", "/projects/{}/{}/briefings"),  # no route yet: tsk-k0k3jzrkpza2, briefings
    ("GET", "/projects/{}/{}/briefings/versions"),  # no route yet: tsk-k0k3jzrkpza2, briefings
    ("GET", "/projects/{}/{}/members/{}/usage"),  # no route yet: tsk-m6sq1g0xwwn5, usage
    ("GET", "/projects/{}/{}/tasks/{}/usage"),  # no route yet: tsk-m6sq1g0xwwn5, usage
    ("GET", "/runner/placements/{}/handover"),  # no route yet: tsk-j9e0yapj21wj
    ("PATCH", "/me/briefings"),  # no route yet: tsk-k0k3jzrkpza2, briefings
    ("PATCH", "/me/preferences"),  # no route yet: tsk-k0k3jzrkpza2, "discuss first"
    ("PATCH", "/projects/{}/{}/briefings"),  # no route yet: tsk-k0k3jzrkpza2, briefings
    ("PATCH", "/projects/{}/{}/conversations/{}/participants/{}"),  # no route yet: tsk-r97n4e6v4kaz
    ("POST", "/agents/{}/soul/rollback"),  # no route yet: tsk-k0k3jzrkpza2, the agent's soul
    ("POST", "/auth/password-reset"),  # no route yet: tsk-pk755085ctff, forgot password
    ("POST", "/auth/password-reset/check"),  # no route yet: tsk-pk755085ctff, forgot password
    ("POST", "/auth/password-reset/complete"),  # no route yet: tsk-pk755085ctff, forgot password
    ("POST", "/projects/{}/{}/claims/renew"),  # no route yet: tsk-p55zyn4pz0wd
    ("POST", "/projects/{}/{}/forge/webhook"),  # before the router: no credential, no CSRF (§17.4)
    ("POST", "/projects/{}/{}/placements/{}/handover"),  # no route yet: tsk-j9e0yapj21wj
    ("POST", "/projects/{}/{}/placements/{}/nudge"),  # no route yet: tsk-j9e0yapj21wj
    ("POST", "/projects/{}/{}/placements/{}/replace"),  # no route yet: tsk-j9e0yapj21wj
    ("POST", "/runner/placements/{}/usage"),  # no route yet: tsk-m6sq1g0xwwn5, usage
    ("PUT", "/me/soul"),  # no route yet: tsk-k0k3jzrkpza2, the agent's soul
    ("PUT", "/runner/placements/{}/handover"),  # no route yet: tsk-j9e0yapj21wj
}

# Routes the contract no longer names, removed with the hub change of the same card. Remove an
# entry when its route goes: the test fails on an entry that no longer applies.
UNLISTED = {
    # The agent writes its soul itself now (§19.1): tsk-k0k3jzrkpza2.
    ("POST", "/me/soul/proposals"),
}


def _index() -> set[tuple[str, str]]:
    """Method and path of the rows of §12. A row outside the API says so, and has no route here.
    Every span counts: a shorthand like `…/steps` would name no route, and so fails the test."""
    text = CONTRACT.read_text(encoding="utf-8").split("## 12. Endpoint index", 1)[1]
    rows = set()
    for line in text.split("\n## 13", 1)[0].splitlines():
        cells = line.split(" | ")
        methods = [m.strip() for m in cells[0].strip("| ").split(",")]
        if len(cells) < 3 or not set(methods) <= set(METHODS):
            # Only the table's head and its rule may go unread: a row of another form names
            # no route the test would check, so it fails here instead of passing unseen.
            head = line.startswith("| Method |") or re.fullmatch(r"\|[-| ]+\|", line)
            assert not line.startswith("|") or head, f"a §12 row that does not parse: {line}"
            continue
        if cells[1].endswith("(outside the API)"):
            continue
        paths = re.findall(r"`([^`]*)`", re.sub(r"\([^)]*\)", "", cells[1]))
        assert paths, f"a §12 row that names no path: {line}"  # else it would check nothing
        for path in paths:
            rows |= {(method, _plain(path)) for method in methods}
    return rows


def _plain(path: str) -> str:
    return re.sub(r"\{[^}]*\}", "{}", path.split("?")[0])


def _routes(openapi: dict[str, Any]) -> set[tuple[str, str]]:
    return {
        (method.upper(), _plain(path.removeprefix("/api/v1")))
        for path, operations in openapi["paths"].items()
        if path.startswith("/api/v1/")
        for method in operations
        if method.upper() in METHODS
    }


@pytest.mark.parametrize(
    "row", ["| UNKNOWN | `/x` | what |", "| GET | /not-real | without its backticks |"]
)
def test_a_row_the_index_cannot_read_fails_it(
    row: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A row that names no route the test can read fails here, instead of checking nothing
    (fmzu at #1482)."""
    contract = tmp_path / "api.md"
    contract.write_text(
        "## 12. Endpoint index\n\n| Method | Path | What |\n|---|---|---|\n"
        f"| GET | `/me` | the caller |\n{row}\n\n## 13. Next\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(sys.modules[__name__], "CONTRACT", contract)
    with pytest.raises(AssertionError, match="§12 row that"):
        _index()


def test_the_index_and_the_routes_name_the_same_endpoints(client: Any) -> None:
    routes = _routes(client.get("/api/v1/openapi.json").json())
    index = _index()
    assert (
        routes - index == UNLISTED
    ), "routes the contract's index does not name, or a stale UNLISTED"
    assert index - routes == NOT_ROUTED, "index rows without a route, or a stale NOT_ROUTED"
