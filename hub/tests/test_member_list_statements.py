"""`GET /projects/{owner}/{slug}/members` builds its member views with one read of the
member humans and the agents' owners, one of their pictures and one of the projects
(tsk-6srccd2r1h62). The owners' rows give their handles and the owner block; the
instances use the projects the views read."""

from __future__ import annotations

import re
import traceback
from collections import Counter
from typing import Any

from sqlalchemy import Engine, event

from tests import flow
from tests.conftest import ClientFactory

MEMBERS = "/projects/maintainer/maity/members"
# Reads are counted by the first table after FROM, and only from inside `member_views`.
_FROM = re.compile(r"^\s*SELECT\b.*?\bFROM\s+(\w+)", re.IGNORECASE | re.DOTALL)


def _reads(engine: Engine, call: Any) -> Counter[str]:
    seen: Counter[str] = Counter()

    def count(_conn: Any, _cursor: Any, statement: str, *_: Any) -> None:
        found = _FROM.match(statement)
        if found and any(f.name == "member_views" for f in traceback.extract_stack()):
            seen[found.group(1)] += 1

    event.listen(engine, "before_cursor_execute", count)
    try:
        response = call()
    finally:
        event.remove(engine, "before_cursor_execute", count)
    assert response.status_code == 200, response.text
    return seen


def test_the_member_list_reads_people_pictures_and_projects_once(
    make_client: ClientFactory, migrated: Engine
) -> None:
    # The owner (members:admin) sees an agent's instances with their credential ids.
    owner = flow.human(make_client, migrated)
    flow.project(owner)
    flow.agent(make_client, owner)
    reads = _reads(migrated, lambda: owner.get(MEMBERS))
    # human: the people read, the briefing writers and the suspensions (moderation);
    # project: the views' read and the full names (namespace.full_names).
    found = (reads["human"], reads["avatar_image"], reads["project"])
    assert found == (3, 1, 2), reads
