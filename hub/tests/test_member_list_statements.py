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


def test_the_member_list_reads_no_more_for_more_agents_with_an_edited_team(
    make_client: ClientFactory, migrated: Engine
) -> None:
    """prod after deploy 5 (tsk-xrtxsvv6f974): a project's member list sent one more statement
    per agent whose team rulebook a human had changed, the editor's handle for
    `team.updated_by`. The people read carries the editors now, so the count stays flat."""
    owner = flow.human(make_client, migrated)
    flow.project(owner)

    def edited_agent() -> None:
        agent = flow.agent(make_client, owner)
        changed = owner.patch(f"{MEMBERS}/{agent.id}", {"team": {"max_instances": 2}})
        assert changed.status_code == 200, changed.text

    edited_agent()
    one = _reads(migrated, lambda: owner.get(MEMBERS))
    edited_agent()
    edited_agent()
    three = _reads(migrated, lambda: owner.get(MEMBERS))
    assert sum(three.values()) == sum(one.values()), (one, three)
    teams = [m["team"]["updated_by"] for m in owner.get(MEMBERS).json()["items"] if "team" in m]
    assert teams and all(
        by == {"kind": "human", "id": owner.id, "handle": "maintainer"} for by in teams
    )
