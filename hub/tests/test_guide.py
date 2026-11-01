"""docs/api.md §5.2: `membership.guide`, what trust and role mean, the same everywhere."""

from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import Engine

from maity_hub import guide, rules
from tests import flow
from tests.conftest import ClientFactory

CONTRACT = Path(__file__).parents[2] / "docs" / "api.md"
PROJECT = SimpleNamespace(roles=[])
LEGAL = SimpleNamespace(
    roles=[{"name": "legal", "base": "reviewer", "guide": "You check.", "guide_by": "oliver"}]
)
BARE = SimpleNamespace(roles=[{"name": "bare", "base": "coder", "guide": "", "guide_by": None}])


def _table(heading: str) -> dict[str, str]:
    lines = CONTRACT.read_text(encoding="utf-8").split(heading, 1)[1].splitlines()[2:]
    rows: dict[str, str] = {}
    for line in lines:
        if not line.strip().startswith("|"):
            return rows
        if found := re.fullmatch(r"\s*\| `([a-z-]+)` \| \"(.*)\" \|", line):
            rows[found[1]] = found[2]
    return rows


def test_the_texts_are_the_contracts_word_for_word() -> None:
    assert _table("| Trust | `guide.trust` |") == guide.TRUST
    assert _table("| Role | `guide.role` |") == guide.ROLE


def test_every_built_in_role_has_a_text() -> None:
    assert set(guide.ROLE) == set(rules._ROLE)


@pytest.mark.parametrize(
    ("trust", "role", "has_trust", "has_role"),
    [
        ("admin", "coder", True, True),
        ("admin", "proxy", False, True),
        ("member", "reviewer", True, True),
        ("guest", "coder", True, False),
    ],
)
def test_each_combination_says_one_thing(
    trust: str, role: str, has_trust: bool, has_role: bool
) -> None:
    found = guide.of(PROJECT, trust, role)
    assert found["trust"] == (guide.TRUST[trust] if has_trust else None)
    assert found["role"] == (guide.ROLE[role] if has_role else None)
    assert found["guide_by"] is None


def test_an_owner_has_no_trust_text() -> None:
    assert guide.of(PROJECT, "owner", "coder")["trust"] is None


def test_a_project_role_brings_its_own_text_and_who_set_it() -> None:
    found = guide.of(LEGAL, "member", "legal")
    assert (found["role"], found["guide_by"]) == ("You check.", "oliver")
    assert guide.of(BARE, "member", "bare")["role"] is None


def test_a_guest_in_a_project_role_gets_neither_its_text_nor_its_author() -> None:
    found = guide.of(LEGAL, "guest", "legal")
    assert (found["role"], found["guide_by"]) == (None, None)


def test_a_bridge_sentence_ends_the_roles_text() -> None:
    assert guide.of(PROJECT, "member", "coder", bridging=True)["role"] == (
        f"{guide.ROLE['coder']} {rules.BRIDGING}"
    )


def test_the_packet_carries_the_guide_and_a_change_shows_on_the_next_resume(
    make_client: ClientFactory, migrated: Engine
) -> None:
    owner = flow.human(make_client, migrated)
    flow.project(owner)
    agent = flow.agent(make_client, owner, trust="member", role="coder")
    first = agent.resume().json()["membership"]["guide"]
    assert first == {
        "trust": guide.TRUST["member"],
        "role": guide.ROLE["coder"],
        "guide_by": None,
    }
    moved = owner.patch(f"/projects/maintainer/maity/members/{agent.id}", {"role": "reviewer"})
    assert moved.status_code == 200, moved.text
    assert agent.resume().json()["membership"]["guide"]["role"] == guide.ROLE["reviewer"]
