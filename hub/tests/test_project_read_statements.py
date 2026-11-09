"""`GET /projects/{owner}/{slug}` resolves the project, the caller's membership and the
owner's handle once each (tsk-6srccd2r1h62). The view's storage figures and restricted
setting use the membership the route read, instead of resolving the project again."""

from __future__ import annotations

import re
import traceback
from collections import Counter
from typing import Any

import pytest
from sqlalchemy import Engine, event

from tests import flow
from tests.conftest import ClientFactory

PROJECT = "/projects/maintainer/maity"
# namespace.resolve reads the whole project row; owner_of reads the owner's handle.
_RESOLVE = re.compile(r"^\s*SELECT project\.id, project\.owner_id\b", re.IGNORECASE)
_OWNER = re.compile(r"^\s*SELECT coalesce\(human\.handle, org\.handle\)", re.IGNORECASE)
_MEMBERSHIP = re.compile(r"^\s*SELECT membership\.id, membership\.project_id\b", re.IGNORECASE)


def _reads(engine: Engine, call: Any) -> Counter[str]:
    """The route's own reads: statements sent from inside `get_project`. Authentication
    reads the project and a membership of its own for an agent (its lease, its project);
    those are not this route's."""
    seen: Counter[str] = Counter()

    def count(_conn: Any, _cursor: Any, statement: str, *_: Any) -> None:
        if not any(frame.name == "get_project" for frame in traceback.extract_stack()):
            return
        for name, pattern in (
            ("resolve", _RESOLVE),
            ("owner", _OWNER),
            ("membership", _MEMBERSHIP),
        ):
            if pattern.match(statement):
                seen[name] += 1

    event.listen(engine, "before_cursor_execute", count)
    try:
        response = call()
    finally:
        event.remove(engine, "before_cursor_execute", count)
    assert response.status_code == 200, response.text
    return seen


@pytest.mark.parametrize("role", ["owner", "member"])
def test_a_project_read_resolves_project_membership_and_owner_once(
    make_client: ClientFactory, migrated: Engine, role: str
) -> None:
    # The owner has project:admin (the storage figures are read); an agent member has not.
    owner = flow.human(make_client, migrated)
    flow.project(owner)
    reader: Any = owner if role == "owner" else flow.agent(make_client, owner)
    reads = _reads(migrated, lambda: reader.get(PROJECT))
    assert (reads["resolve"], reads["membership"], reads["owner"]) == (1, 1, 1), reads
