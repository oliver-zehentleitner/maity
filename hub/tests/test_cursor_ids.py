"""docs/api.md §1.4: a time cursor (`paging.cursor`) whose id holds a lone surrogate or a NUL
is refused as 400 `invalid` on every route that reads one, before its id reaches a query.
Such an id is no text a driver binds: a lone surrogate does not encode as UTF-8 and
PostgreSQL refuses a NUL in text, so the client got a 500 (tsk-tjjgzhepgpdp). Each case
first pages with a well-formed id under the same scope, so the refusal is the id's and not
a cursor bound to other filters."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import Engine

from maity_hub import contacts, paging
from maity_hub.routes.conversations import _BAND_ORDER
from tests import flow
from tests.conftest import ClientFactory

PROJECT = "/projects/maintainer/maity"

# Each route that reads a time cursor: its path, the scope it binds the cursor to, and how
# its id is built from a card-like id (some carry more than an id in it).
ROUTES: dict[str, tuple[str, str | None, str]] = {
    "tasks-updated": (
        f"{PROJECT}/tasks?order=updated",
        paging.scope(
            status="all",
            kind=None,
            label=None,
            needs=None,
            holder=None,
            assigned_to=None,
            area=None,
            parent=None,
            closed_after=None,
            order="updated",
        ),
        "{}",
    ),
    "runner-enrollments": ("/runners/enrollments", None, "{}"),
    "conversations": (
        f"{PROJECT}/conversations",
        paging.scope(observed=False, bands=_BAND_ORDER),
        "0\x1f{}",
    ),
    "takeovers": (f"{PROJECT}/takeovers", paging.scope(status="open", task_id=None), "{}"),
    "admin-reports": (
        "/admin/reports",
        paging.scope(list="admin/reports", status="all", type=None),
        "0:{}",
    ),
    "contacts": ("/me/contacts", paging.scope(list=contacts.CONTACTS), "{}"),
    "admin-orgs": ("/admin/orgs", paging.scope(list="admin/orgs", q=None, suspended=None), "{}"),
    "maintenance-changes": ("/admin/maintenance/changes", None, "{}"),
}


@pytest.fixture
def admin(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    """The instance admin (the earliest account), owner of a project."""
    human = flow.human(make_client, migrated)
    flow.project(human)
    return human


@pytest.mark.parametrize("route", ROUTES)
@pytest.mark.parametrize("bad", ["tsk-\ud800x", "tsk-\x00x"], ids=["lone-surrogate", "nul"])
def test_a_cursor_whose_id_no_driver_binds_is_invalid(
    admin: flow.Human, route: str, bad: str
) -> None:
    path, bound, shape = ROUTES[route]
    at = datetime.now(UTC)
    joiner = "&" if "?" in path else "?"
    good = admin.get(f"{path}{joiner}cursor={paging.cursor(at, shape.format('tsk-x'), bound)}")
    assert good.status_code == 200, good.text
    refused = admin.get(f"{path}{joiner}cursor={paging.cursor(at, shape.format(bad), bound)}")
    assert refused.status_code == 400, refused.text
    assert refused.json()["error"]["code"] == "invalid"
    assert refused.json()["error"]["details"]["fields"] == {"cursor": "invalid"}
