"""docs/api.md §16.9, "A report link": the pages of a project and its views, a card, an agent and a
person carry under their title a link Report to the sign-in, whose way back is the same address
with `?report`; a person's agents page carries none."""

from __future__ import annotations

from dataclasses import replace
from typing import Any
from urllib.parse import quote

import pytest
from sqlalchemy import Engine, select

from maity_hub import public_pages
from maity_hub import tables as t
from tests.conftest import ClientFactory
from tests.test_public_project_views import BASE, TASKS, World


@pytest.fixture
def world(make_client: ClientFactory, migrated: Engine, settings: Any) -> World:
    public_pages.configure(replace(settings, public_pages=True))
    return World(make_client, migrated)


def link(path: str) -> str:
    """The link as the contract gives it, the page's language added as on every sign-in link."""
    back = quote(f"{path}?report", safe="")
    href = f"/login?next={back}&amp;lang=en"
    return f'<p class="report-link"><a href="{href}" rel="nofollow">Report</a></p>'


def page(world: World, path: str) -> str:
    got = world.anyone.get(path)
    assert got.status_code == 200, got.text
    assert "<title>dashboard</title>" not in got.text, f"{path} is not served"
    return str(got.text)


def test_the_project_page_and_each_public_view_carry_the_link_under_the_title(world: World) -> None:
    for path in (BASE, f"{BASE}/board", f"{BASE}/team", f"{BASE}/organisation", f"{BASE}/why"):
        text = page(world, path)
        assert link(path) in text, path
        assert text.index("</h1>") < text.index(link(path)), path
    assert link(BASE) == (
        '<p class="report-link"><a href="/login?next=%2Fmaintainer%2Fmaity%3Freport&amp;lang=en"'
        ' rel="nofollow">Report</a></p>'
    )


def test_a_card_page_carries_the_link_to_its_own_address(world: World) -> None:
    made = world.owner.post(TASKS, {"title": "Fix the pager"})
    assert made.status_code == 201, made.text
    path = f"{BASE}/tasks/{made.json()['id']}"
    assert link(path) in page(world, path)


def test_a_person_and_an_agent_carry_it_and_the_agents_page_does_not(world: World) -> None:
    assert link("/maintainer") in page(world, "/maintainer")
    with world.migrated.connect() as conn:
        handle = conn.execute(select(t.agent_profile.c.handle)).scalar_one()
    path = f"/maintainer/agents/{handle}"
    assert link(path) in page(world, path)
    assert "report-link" not in page(world, "/maintainer/agents")
