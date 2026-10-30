"""The duty line of the generated rules follows `hints.duty` (docs/api.md §6.9, §5.2, §15.11,
tsk-n6b8q0tz9yt2)."""

from __future__ import annotations

from sqlalchemy import Engine

from maity_hub import rules
from tests import flow
from tests.conftest import ClientFactory


def test_a_session_that_waits_for_itself_gets_the_self_duty_line(
    make_client: ClientFactory, migrated: Engine
) -> None:
    owner = flow.human(make_client, migrated)
    flow.project(owner, "maity")
    agent = flow.agent(make_client, owner)
    packet = agent.resume().json()
    assert packet["hints"]["duty"] == "self"
    markdown = packet["rules"]["markdown"]
    assert "## On duty" in markdown and rules.DUTY_SELF in markdown
    assert "## Supervised" not in markdown
    assert rules.DUTY_SELF in owner.get("/projects/maintainer/maity/rules").text
    for kept in ("`maity wait`", "`hints.wait_timeout`", "shortly before your next run"):
        assert kept in rules.DUTY_SELF


def test_a_supervised_session_gets_the_supervised_line_and_not_the_self_one() -> None:
    project = type(
        "P",
        (),
        {
            "name": "p", "rules_version": 1, "state": "build", "state_note": None,
            "released_at": None, "policy_preset": "x", "claim_policy": "x", "done_authority": "x",
            "tag_authority": "x", "steward_writes": "x", "lease_seconds": 60,
            "keep_the_why": False, "rules_markdown": None,
        },
    )()  # fmt: skip
    text = rules.generate(project, "member", "coder", "the owner", supervised=True)
    assert rules.SUPERVISED in text and "## Supervised" in text
    assert "## On duty" not in text and rules.DUTY_SELF not in text


def test_the_rules_route_follows_the_session_of_its_caller(
    make_client: ClientFactory, migrated: Engine
) -> None:
    owner = flow.human(make_client, migrated)
    flow.project(owner, "maity")
    agent = flow.agent(make_client, owner)
    path = "/projects/maintainer/maity/rules"
    assert agent.resume().status_code == 200
    plain = agent.get(path).text
    assert rules.DUTY_SELF in plain and "## Supervised" not in plain
    assert agent.resume(supervisor="maity-runner/0.1.0").status_code == 200
    supervised = agent.get(path).text
    assert rules.SUPERVISED in supervised and rules.DUTY_SELF not in supervised
    assert rules.DUTY_SELF in owner.get(path).text  # a human reads the self line
