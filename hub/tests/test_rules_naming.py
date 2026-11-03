"""The naming line of the generated rules (docs/api.md §6.9, tsk-m01hs0w91zv6)."""

from __future__ import annotations

from types import SimpleNamespace

from sqlalchemy import Engine

from maity_hub import rules
from tests import flow
from tests.conftest import ClientFactory


def _project(**overrides: object) -> SimpleNamespace:
    fields = {
        "name": "p", "rules_version": 1, "state": "build", "state_note": None,
        "released_at": None, "policy_preset": "x", "claim_policy": "x", "done_authority": "x",
        "tag_authority": "x", "steward_writes": "x", "lease_seconds": 60,
        "keep_the_why": True, "rules_markdown": "owner text", "roles": None,
    }  # fmt: skip
    fields.update(overrides)
    return SimpleNamespace(**fields)


def test_every_role_gets_the_naming_line_before_the_owners_text() -> None:
    for role in ("coder", "reviewer", "tester", "manager", "writer"):
        for supervised in (False, True):
            text = rules.generate(_project(), "member", role, "the owner", supervised=supervised)
            assert text.count(rules.NAMING) == 1
            naming = text.index("## Naming members")
            assert text.index("## Keep the Why") < naming < text.index("## From the owner")


def test_the_naming_line_stands_without_owner_text_or_keep_the_why() -> None:
    text = rules.generate(_project(keep_the_why=False, rules_markdown=None), "member", "coder", "x")
    assert text.rstrip().endswith(rules.NAMING)


def test_the_naming_line_says_what_the_contract_says() -> None:
    for kept in (
        "a human may read",
        "between agents",
        "a group chat",
        "review result",
        "`handle#instance`",
        "never by the instance suffix or the member id alone",
        "`to`",
    ):
        assert kept in rules.NAMING


def test_the_resume_packet_and_the_rules_route_carry_the_naming_line(
    make_client: ClientFactory, migrated: Engine
) -> None:
    owner = flow.human(make_client, migrated)
    flow.project(owner, "maity")
    agent = flow.agent(make_client, owner)
    assert rules.NAMING in agent.resume().json()["rules"]["markdown"]
    assert rules.NAMING in agent.get("/projects/maintainer/maity/rules").text
