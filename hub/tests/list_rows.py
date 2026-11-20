"""A list costs the same statements for 3 rows as for 30: the claim a test makes with
`@flat_rows("/route")`, and the measurement it makes it with (`same_for_3_and_30`).

`tests/test_list_rows.py` holds the guard: every GET route under `/api/v1/` that answers a
list (`items`) is named by a `@flat_rows` test, or is in its `NOT_LISTS` or `CATALOGS`. Why 3
and 30, and how the routes are found: `hub/context/testing.md`."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypeVar

import pytest
from sqlalchemy import Engine

from tests.statements import count_statements

F = TypeVar("F", bound=Callable[..., Any])

# Known exceptions: list routes whose statements grow with their rows today (measured
# 2026-11-20, tsk-xdn21ph67js9). Each gets its own card for the fix; its `@flat_rows` test still
# runs and asserts that the cost grows, so an entry fails once its fix lands and leaves with that
# card. One per line, sorted, with what the route reads per row.
GROWING: dict[str, str] = {
    "/admin/registrations": "the account (`registration_accounts.item`)",
    "/admin/reports": "the project's name, the reporter's handle (`reports.admin_view`)",
    "/agents": "the agent's view (`views.agent_view`)",
    "/agents/{}/soul/versions": "`by` and `confirmed_by` (`memory.who`)",
    "/me/contact-of": "the person's picture (`routes.people._avatar`)",
    "/me/contacts": "the person's picture (`routes.people._avatar`)",
    "/me/cross-chats": "who stays (`cross_chats.stays`), and one more read",
    "/me/preferences/versions": "the author (`preferences._handle`)",
    "/me/reports": "the target (`reports._public_target`)",
    "/orgs": "pictures, aliases, moderation hold (`orgs.view`)",
    "/orgs/{}/members/invitations": "the inviter (`org_invitations.view`)",
    "/projects": "restricted fields, confirmations (`routes.projects.list_projects`)",
    "/projects/{}/{}/attachments": "the attachment's view (`attachments.view`, one row a call)",
    "/projects/{}/{}/jour-fixe/series": "grants, recipients, opt-outs (`series.view`)",
    "/projects/{}/{}/members/{}/credentials": "session and principal (`views.credential_view`)",
    "/projects/{}/{}/placements": "the placement's view (`routes.placements._view`)",
    "/projects/{}/{}/runners": "the attachment's view (`routes.runners.attachment_view`)",
    "/projects/{}/{}/takeovers": "members and principals (`takeovers.view`)",
    "/runner/placements": "the placement's view (`routes.runner.runner_placements`)",
    "/runners": "the runner's view (`routes.runners.runner_view`)",
    "/runners/{}/placements": "the owner line (`placements.owner_line`)",
}


def flat_rows(*routes: str) -> Callable[[F], F]:
    """Mark a test as the one that shows `routes` (as `/path/{}` with `{}` for every
    parameter, without `/api/v1`) cost the same for 3 rows as for 30. The guard reads these
    decorators from the source, so the routes must be string literals."""
    assert routes, "name the routes the test measures"
    marker: Callable[[F], F] = pytest.mark.flat_rows(*routes)
    return marker


def _rows(answer: Any) -> int:
    rows = answer.json()["items"]
    assert isinstance(rows, list), answer.text
    return len(rows)


def same_for_3_and_30(
    engine: Engine,
    route: str,
    call: Callable[[], Any],
    grow: Callable[[int], None],
    rows: Callable[[Any], int] = _rows,
    async_engines: bool = False,
) -> tuple[int, int]:
    """`call` answers 200 with `grow(3)` more rows and again with `grow(27)` more, the list
    showing 27 rows more the second time, and sends the same number of statements both times
    (more, for a route in `GROWING`). One call before, so a one-time write of a first read (a
    presence, a baseline) is not taken for row cost. Without `async_engines` the statements on
    the app's async engine (the sign-in, whose presence write comes once a minute) are not
    counted, as in `test_view_batching`: a route that reads there passes `True`. Returns the
    two counts."""
    first = call()
    assert first.status_code == 200, first.text
    measured: list[Any] = []

    def counted() -> tuple[int, int]:
        seen = count_statements(engine, lambda: measured.append(call()), async_engines)
        answer = measured.pop()
        assert answer.status_code == 200, answer.text
        return seen, rows(answer)

    grow(3)
    small, few = counted()
    grow(27)
    large, many = counted()
    assert many - few == 27, f"{route}: the list shows {few} and then {many} rows, not 27 more"
    assert small > 0, f"{route}: no statement counted; does it read on the async engine?"
    if route in GROWING:
        assert large > small, (
            f"{route}: {small} statements for 3 rows and {large} for 30, the same now: "
            "remove it from GROWING (tests/list_rows.py)"
        )
    else:
        assert large == small, f"{route}: {small} statements for 3 rows, {large} for 30"
    return small, large
