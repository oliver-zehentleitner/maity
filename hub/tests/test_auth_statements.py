"""A dashboard call's authentication reads the session, the human and the instance settings
once each (tsk-6srccd2r1h62). It runs before every route of a signed-in human, so each
statement it repeats is paid on every call."""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

import pytest
from sqlalchemy import Engine, event

from maity_hub import instance_settings
from tests import flow
from tests.conftest import ClientFactory

# A route whose own work reads neither the sessions nor the settings, and the human table
# once: the project's owner by handle (namespace.resolve). Every other read counted is the
# authentication's. Reads are counted by the first table after FROM, so the session read,
# which joins its human, counts as `human_session`.
TASKS = "/projects/maintainer/maity/tasks"
_FROM = re.compile(r"^\s*SELECT\b.*?\bFROM\s+(\w+)", re.IGNORECASE | re.DOTALL)


def _reads(engine: Engine, call: Any) -> Counter[str]:
    """The SELECTs `call` sends, by the first table after FROM."""
    seen: Counter[str] = Counter()

    def count(_conn: Any, _cursor: Any, statement: str, *_: Any) -> None:
        found = _FROM.match(statement)
        if found:
            seen[found.group(1)] += 1

    event.listen(engine, "before_cursor_execute", count)
    try:
        response = call()
    finally:
        event.remove(engine, "before_cursor_execute", count)
    assert response.status_code == 200, response.text
    return seen


@pytest.mark.parametrize("policy", ["optional", "off"])
def test_a_cookie_call_reads_session_human_and_settings_once(
    make_client: ClientFactory, migrated: Engine, policy: str
) -> None:
    # `optional` (the default) asks whether the human must enrol; `off` asks nothing.
    owner = flow.human(make_client, migrated)
    flow.project(owner)
    with migrated.begin() as conn:
        instance_settings.put(conn, "sign_in.second_factor", policy, None)
    reads = _reads(migrated, lambda: owner.get(TASKS))
    assert (reads["human_session"], reads["human"], reads["instance_setting"]) == (1, 1, 1), reads
