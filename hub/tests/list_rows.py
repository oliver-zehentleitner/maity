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

from tests.statements import listening

F = TypeVar("F", bound=Callable[..., Any])

# Known exceptions: list routes whose statements grow with their rows today (measured
# 2026-11-20, tsk-xdn21ph67js9; the last six after the reviews of #2039). Each gets its own card
# for the fix; its `@flat_rows` test still runs and asserts that the cost grows, so an entry fails
# once its fix lands and leaves with that card. One per line, sorted, with what the route reads
# per row. `<route> [<case>]`: only that way of reading the route grows (`same_for_3_and_30`).
GROWING: dict[str, str] = {
    "/admin/registrations": "the account (`registration_accounts.item`)",
    "/admin/reports": "the project's name, the reporter's handle (`reports.admin_view`)",
    "/agents": "the agent's view (`views.agent_view`)",
    "/agents/{}/soul/versions": "`by` and `confirmed_by` (`memory.who`)",
    "/me": "the open requests of each project (`inbox.open_requests`)",
    "/me/contact-of": "the person's picture (`routes.people._avatar`)",
    "/me/contacts": "the person's picture (`routes.people._avatar`)",
    "/me/cross-chats": "who stays (`cross_chats.stays`), and one more read",
    "/me/preferences/versions": "the author (`preferences._handle`)",
    "/me/reports": "the target (`reports._public_target`)",
    "/orgs": "pictures, aliases, moderation hold (`orgs.view`)",
    "/orgs/{}/members/invitations": "the inviter (`org_invitations.view`)",
    "/projects": "restricted fields, confirmations (`routes.projects.list_projects`)",
    "/projects/{}/{}/attachments": "the attachment's view (`attachments.view`, one row a call)",
    "/projects/{}/{}/jour-fixe": "`_shown`, `rounds.current`, `_last_reported`, `_views`",
    "/projects/{}/{}/jour-fixe/rounds [owner circle, read by the moderator]": "`circle.reads`",
    "/projects/{}/{}/jour-fixe/rounds [owner circle, read by the owned agent]": "`circle.reads`",
    "/projects/{}/{}/jour-fixe/series": "grants, recipients, opt-outs (`series.view`)",
    "/projects/{}/{}/limits": "ceilings, instances held (`project_limits._agents`)",
    "/projects/{}/{}/members/{}/credentials": "session and principal (`views.credential_view`)",
    "/projects/{}/{}/placements": "the placement's view (`routes.placements._view`)",
    "/projects/{}/{}/runners": "the attachment's view (`routes.runners.attachment_view`)",
    "/projects/{}/{}/takeovers": "members and principals (`takeovers.view`)",
    "/runner/placements": "the placement's view (`routes.runner.runner_placements`)",
    "/runners": "the runner's view (`routes.runners.runner_view`)",
    "/runners/enrollments": "the attached projects' names (`namespace.full_names`)",
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
    case: str = "",
) -> tuple[int, int]:
    """`call` answers 200 with `grow(3)` more rows and again with `grow(27)` more, the list
    showing 27 rows more the second time, and sends the same number of statements both times
    (more, for a route in `GROWING`). One call before, so a one-time write of a first read (a
    presence, a baseline) is not taken for row cost. Without `async_engines` the statements on
    the app's async engine (the sign-in, whose presence write comes once a minute) are not
    counted, as in `test_view_batching`: a route that reads there passes `True`. A `case`
    names one way to read the route that costs differently from the others (another reader):
    GROWING then lists `"<route> [<case>]"` alone, and the route's other tests stay flat.
    Returns the two counts."""
    first = call()
    assert first.status_code == 200, first.text
    measured: list[Any] = []

    def counted() -> tuple[int, int]:
        seen = [0]

        def heard(conn: Any, cursor: Any, statement: str, *_: Any) -> None:
            # SQLite's `PRAGMA query_only`, switched on a pooled connection whose last use was a
            # write (`db.read_transaction`): which connection the pool hands out decides it, not
            # the rows. Seen with a minute between the two counts of `…/overview`.
            if not statement.lstrip().upper().startswith("PRAGMA"):
                seen[0] += 1

        with listening(engine, heard, async_engines):
            measured.append(call())
        answer = measured.pop()
        assert answer.status_code == 200, answer.text
        return seen[0], rows(answer)

    grow(3)
    small, few = counted()
    grow(27)
    large, many = counted()
    assert many - few == 27, f"{route}: the list shows {few} and then {many} rows, not 27 more"
    assert small > 0, f"{route}: no statement counted; does it read on the async engine?"
    known = f"{route} [{case}]" if case else route
    if known in GROWING:
        assert large > small, (
            f"{known}: {small} statements for 3 rows and {large} for 30, the same now: "
            "remove it from GROWING (tests/list_rows.py)"
        )
    else:
        assert large == small, f"{known}: {small} statements for 3 rows, {large} for 30"
    return small, large
