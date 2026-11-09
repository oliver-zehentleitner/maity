"""A dashboard call's authentication reads the session, the human and the instance settings
once each (tsk-6srccd2r1h62). It runs before every route of a signed-in human, so each
statement it repeats is paid on every call."""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

import pytest
from sqlalchemy import Engine, event, update

from maity_hub import clock, instance_settings
from maity_hub import tables as t
from tests import flow
from tests.conftest import ClientFactory

# A route whose own work reads neither the sessions nor the settings, and the human table
# once: the project's owner by handle (namespace.resolve). Every other read counted is the
# authentication's. Reads are counted by the first table after FROM, so the session read,
# which joins its human, counts as `human_session`.
TASKS = "/projects/maintainer/maity/tasks"
NOTIFICATIONS = "/me/notifications"  # one of the calls a moved session keeps (§2.8.5)
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


def test_a_confirmation_committed_just_before_the_call_counts(
    make_client: ClientFactory, migrated: Engine
) -> None:
    # #1540 review: the gate decides on the session as it stands once the call's own writes
    # locked it, as its own read did before the reads were shared. A device-code sign-in of
    # a project owner without a factor, under `required_admins`, is moved into enrolment;
    # confirmed ("This was me") it is in good standing and keeps its notifications (§2.8.5).
    if migrated.dialect.name == "sqlite":
        pytest.skip("a commit between two statements of a call needs a second writer")
    owner = flow.human(make_client, migrated)
    flow.project(owner)
    session = t.human_session.c
    with migrated.begin() as conn:
        instance_settings.put(conn, "sign_in.second_factor", "required_admins", None)
        conn.execute(
            update(t.human_session)
            .where(session.human_id == owner.id)
            .values(method="device_code", confirmed_at=None, confirmed_by=None)
        )
    refused = owner.get(NOTIFICATIONS)
    assert refused.status_code == 403, refused.text  # unconfirmed: no standing
    fired: list[str] = []

    def confirm(_conn: Any, _cursor: Any, statement: str, *_: Any) -> None:
        # Another session confirms this one just before the call's first session write.
        if fired or not statement.lstrip().startswith("UPDATE human_session"):
            return
        fired.append(statement)
        with migrated.begin() as other:
            other.execute(
                update(t.human_session)
                .where(session.human_id == owner.id)
                .values(confirmed_at=clock.now(), confirmed_by="ses-other")
            )

    event.listen(migrated, "before_cursor_execute", confirm)
    try:
        answered = owner.get(NOTIFICATIONS)
    finally:
        event.remove(migrated, "before_cursor_execute", confirm)
    assert fired, "the call wrote no session"
    assert answered.status_code == 200, answered.text
