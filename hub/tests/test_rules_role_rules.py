"""Role rules: rule lines a project sets per role (docs/api.md §6.1 "Role rules", §6.9;
tsk-ebvf65axtwes)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import Engine, select

from maity_hub import rules
from maity_hub import tables as t
from tests import factory, flow
from tests.conftest import ClientFactory

BASE = "/projects/maintainer/maity"
SET = {
    "coder": {"subagent_per_card": True},
    "reviewer": {"subagent_per_card": True, "checklist": ["a test fails without it", "changelog"]},
    "tester": {"checklist": ["run the e2e suite against the head"]},
}
HEADING = "## Set by the project for your role"


def _project(**overrides: object) -> SimpleNamespace:
    fields = {
        "name": "p", "rules_version": 1, "state": "build", "state_note": None,
        "released_at": None, "policy_preset": "x", "claim_policy": "x", "done_authority": "x",
        "tag_authority": "x", "steward_writes": "x", "lease_seconds": 60,
        "keep_the_why": True, "rules_markdown": "owner text", "roles": None,
        "settings": {"role_rules": SET},
    }  # fmt: skip
    fields.update(overrides)
    return SimpleNamespace(**fields)


def _section(text: str) -> str:
    """The role lines' section, up to the owner's text."""
    return text[text.index(HEADING) : text.index("## From the owner")]


def test_each_role_reads_its_own_lines_after_the_naming_line() -> None:
    coder = rules.generate(_project(), "member", "coder", "x")
    assert coder.index("## Naming members") < coder.index(HEADING)
    assert coder.index(HEADING) < coder.index("## From the owner")
    assert _section(coder) == f"{HEADING}\n\n{rules.SUBAGENT}\n\n"
    reviewer = _section(rules.generate(_project(), "member", "reviewer", "x"))
    assert reviewer == (
        f"{HEADING}\n\n{rules.SUBAGENT}\n\n{rules.SUBAGENT_REVIEW}\n\n"
        "- In every review, check: a test fails without it\n"
        "- In every review, check: changelog\n\n"
    )
    tester = _section(rules.generate(_project(), "member", "tester", "x"))
    assert tester == f"{HEADING}\n\n- In every test, check: run the e2e suite against the head\n\n"


@pytest.mark.parametrize(
    ("role", "reads_as"),
    [("blue-team", "coder"), ("purple-team", "reviewer"), ("red-team", "tester")],
)
def test_a_security_team_reads_the_lines_of_the_role_it_counts_as(role: str, reads_as: str) -> None:
    project = _project()
    assert _section(rules.generate(project, "member", role, "x")) == _section(
        rules.generate(project, "member", reads_as, "x")
    )


def test_a_project_role_reads_the_lines_of_its_base() -> None:
    roles = [{"name": "legal", "base": "purple-team", "guide": None, "guide_by": None}]
    project = _project(roles=roles)
    assert _section(rules.generate(project, "member", "legal", "x")) == _section(
        rules.generate(project, "member", "reviewer", "x")
    )


@pytest.mark.parametrize("role", ["manager", "writer", "ops", "designer", "proxy", "unknown"])
def test_a_role_that_is_none_of_the_three_gets_no_lines(role: str) -> None:
    assert HEADING not in rules.generate(_project(), "member", role, "x")


@pytest.mark.parametrize(
    "stored",
    [None, {}, {"role_rules": {}}, {"role_rules": {"coder": {}}},
     {"role_rules": {"coder": {"subagent_per_card": False}, "tester": {"checklist": []}}}],
)  # fmt: skip
def test_nothing_set_adds_no_section(stored: Any) -> None:
    project = _project(settings=stored)
    for role in ("coder", "tester"):
        assert HEADING not in rules.generate(project, "member", role, "x")


def test_the_lines_say_what_the_contract_says() -> None:
    for kept in (
        "a subagent with a fresh context, one subagent per card",
        "the subagent never does",
        "the diff or the cites",
        "`Ran`",
        "what it learned",
        "check that report before you send anything from it",
    ):
        assert kept in rules.SUBAGENT
    assert "never in your own" in rules.SUBAGENT_REVIEW
    assert rules.CHECKLIST == {
        "reviewer": "In every review, check:",
        "tester": "In every test, check:",
    }


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    human = flow.human(make_client, migrated)
    flow.project(human)
    return human


def _events(engine: Engine, kind: str) -> list[Any]:
    with engine.connect() as conn:
        return list(
            conn.execute(select(t.event).where(t.event.c.kind == kind).order_by(t.event.c.seq))
        )


def _version(engine: Engine) -> int:
    with engine.connect() as conn:
        return int(conn.execute(select(t.project.c.rules_version)).scalar_one())


def test_set_read_and_served_to_the_role(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    reviewer = flow.agent(make_client, owner, role="reviewer")
    coder = flow.agent(make_client, owner, role="coder")
    assert "role_rules" not in owner.get(BASE).json()["settings"]
    before = _version(migrated)
    response = owner.patch(BASE, {"settings": {"role_rules": SET}})
    assert response.status_code == 200, response.text
    assert response.json()["settings"]["role_rules"] == SET
    assert coder.get(BASE).json()["settings"]["role_rules"] == SET
    assert _version(migrated) == before + 1
    [updated] = [
        e
        for e in _events(migrated, "project_updated")
        if "settings.role_rules" in e.payload["fields"]
    ]
    assert updated.payload == {
        "fields": {
            "settings.role_rules": {
                "coder": {"subagent_per_card": True},
                "reviewer": {"subagent_per_card": True, "checklist": True},
                "tester": {"checklist": True},
            }
        }
    }
    assert _events(migrated, "rules_changed")[-1].payload == {
        "version": before + 1,
        "reason": "settings.role_rules",
    }
    text = reviewer.get(f"{BASE}/rules").text
    assert rules.SUBAGENT_REVIEW in text
    assert "- In every review, check: a test fails without it" in text
    assert reviewer.resume().json()["rules"]["markdown"].count(HEADING) == 1
    coder_text = coder.get(f"{BASE}/rules").text
    assert rules.SUBAGENT in coder_text and rules.SUBAGENT_REVIEW not in coder_text


def test_the_same_value_again_changes_nothing_and_null_removes(
    owner: flow.Human, migrated: Engine
) -> None:
    owner.patch(BASE, {"settings": {"role_rules": SET}})
    before = _version(migrated)
    count = len(_events(migrated, "project_updated"))
    assert owner.patch(BASE, {"settings": {"role_rules": SET}}).status_code == 200
    assert owner.patch(BASE, {"settings": {"language": "de"}}).status_code == 200
    assert _version(migrated) == before
    assert len(_events(migrated, "project_updated")) == count + 1  # the language alone
    removed = owner.patch(BASE, {"settings": {"role_rules": None}})
    assert "role_rules" not in removed.json()["settings"]
    assert _events(migrated, "project_updated")[-1].payload == {
        "fields": {"settings.role_rules": None}
    }
    assert _version(migrated) == before + 1


def test_a_value_without_effect_is_kept_but_moves_no_rules_version(
    owner: flow.Human, migrated: Engine
) -> None:
    """`false` and `[]` read as every rule off, as an absent key does: stored as given (the hub
    never filters silently), announced as a settings change, but the rules text is the same,
    so `rules_version` stays (c47w at #1279: {} → false → [] went 1 → 4)."""
    before = _version(migrated)
    count = len(_events(migrated, "rules_changed"))
    announced = len(_events(migrated, "project_updated"))
    values: tuple[dict[str, Any] | None, ...] = (
        {"coder": {"subagent_per_card": False}},
        {"coder": {"subagent_per_card": False}, "reviewer": {"checklist": []}},
        {"reviewer": {}},
        None,
    )
    for value in values:
        answer = owner.patch(BASE, {"settings": {"role_rules": value}})
        assert answer.status_code == 200, answer.text
        assert answer.json()["settings"].get("role_rules") == value
    assert _version(migrated) == before
    assert len(_events(migrated, "rules_changed")) == count
    updated = _events(migrated, "project_updated")[announced:]
    assert [u.payload["fields"] for u in updated] == [
        {"settings.role_rules": {"coder": {"subagent_per_card": False}}},
        {
            "settings.role_rules": {
                "coder": {"subagent_per_card": False},
                "reviewer": {"checklist": True},
            }
        },
        {"settings.role_rules": {"reviewer": {}}},
        {"settings.role_rules": None},
    ]
    assert owner.patch(BASE, {"settings": {"role_rules": SET}}).status_code == 200
    assert _version(migrated) == before + 1  # a value with effect still moves it


def test_one_patch_with_other_rules_inputs_bumps_once_with_its_own_reason(
    owner: flow.Human, migrated: Engine
) -> None:
    before = _version(migrated)
    count = len(_events(migrated, "rules_changed"))
    body = {"settings": {"role_rules": SET}, "rules_markdown": "new", "reason": "tighter reviews"}
    assert owner.patch(BASE, body).status_code == 200
    assert _version(migrated) == before + 1
    changed = _events(migrated, "rules_changed")
    assert len(changed) == count + 1
    assert changed[-1].payload == {"version": before + 1, "reason": "tighter reviews"}


def test_a_value_without_effect_does_not_name_the_bump_another_input_made(
    owner: flow.Human, migrated: Engine
) -> None:
    """The reason `settings.role_rules` is for a PATCH whose role rules changed the rules;
    one whose role rules added nothing leaves the bump to the input that made it (e5kk at
    #1486)."""
    before = _version(migrated)
    body = {"settings": {"role_rules": {"coder": {"subagent_per_card": False}}}}
    assert owner.patch(BASE, {**body, "rules_markdown": "new"}).status_code == 200
    assert _version(migrated) == before + 1
    assert _events(migrated, "rules_changed")[-1].payload == {"version": before + 1}


@pytest.mark.parametrize(
    ("body", "marks"),
    [
        ({"settings": {"role_rules": SET}, "state": "review"}, ["state_changed"]),
        (
            {"settings": {"role_rules": SET}, "policy": {"done_authority": "tester"}},
            ["policy_changed"],
        ),
        (
            {"state": "review", "policy": {"done_authority": "tester"}, "rules_markdown": "new"},
            ["state_changed", "policy_changed"],
        ),
    ],
)
def test_a_patch_with_its_own_rules_event_still_bumps_once(
    owner: flow.Human, migrated: Engine, body: dict[str, Any], marks: list[str]
) -> None:
    """A state_changed or policy_changed marks the PATCH's one new version; the rules inputs
    beside it write no rules_changed of their own (§6.1)."""
    before = _version(migrated)
    count = len(_events(migrated, "rules_changed"))
    response = owner.patch(BASE, {**body, "reason": "both"})
    assert response.status_code == 200, response.text
    assert _version(migrated) == before + 1
    assert len(_events(migrated, "rules_changed")) == count
    for kind in marks:
        assert _events(migrated, kind)[-1].payload["rules_version"] == before + 1
    with migrated.connect() as conn:
        marker = conn.execute(select(t.project.c.rules_changed_seq)).scalar_one()
    assert marker == _events(migrated, marks[-1])[-1].seq


def test_items_are_stored_trimmed_up_to_the_limits(owner: flow.Human) -> None:
    longest = "x" * 300
    items = [f"  {longest}  ", *(f"item {n}" for n in range(29))]
    response = owner.patch(BASE, {"settings": {"role_rules": {"tester": {"checklist": items}}}})
    assert response.status_code == 200, response.text
    stored = response.json()["settings"]["role_rules"]["tester"]["checklist"]
    assert stored[0] == longest and len(stored) == 30


@pytest.mark.parametrize("blank", ["\u3164", "\u2800", "\u115f\u1160", "\u034f"])
def test_only_the_four_categories_are_checked_so_a_blank_looking_item_is_stored(
    owner: flow.Human, blank: str
) -> None:
    """§6.1: Cc, Cf, Zl and Zp are refused; a character outside them that shows nothing counts
    as text, as the contract says, so the item is stored, not `empty_item`."""
    response = owner.patch(BASE, {"settings": {"role_rules": {"tester": {"checklist": [blank]}}}})
    assert response.status_code == 200, response.text
    assert response.json()["settings"]["role_rules"]["tester"]["checklist"] == [blank]


@pytest.mark.parametrize(
    ("role", "rules_in", "field", "error"),
    [
        ("designer", {"subagent_per_card": True}, "", "unknown_role"),
        ("purple-team", {}, "", "unknown_role"),
        ("coder", {"checklist": ["x"]}, ".checklist", "not_allowed"),
        ("tester", {"checklist": ["x", "   "]}, ".checklist", "empty_item"),
        ("tester", {"checklist": ["a\nb"]}, ".checklist", "multiline"),
        ("tester", {"checklist": ["a\tb"]}, ".checklist", "multiline"),
        ("tester", {"checklist": ["a\u2028b"]}, ".checklist", "multiline"),
        ("tester", {"checklist": ["a\u202eb"]}, ".checklist", "multiline"),
        ("tester", {"checklist": ["a\u200bb"]}, ".checklist", "multiline"),
        ("tester", {"checklist": ["a\u2066b"]}, ".checklist", "multiline"),
        ("tester", {"checklist": ["\ufeffab"]}, ".checklist", "multiline"),
        ("tester", {"checklist": ["a\u061cb"]}, ".checklist", "multiline"),
        ("tester", {"checklist": ["a\u180eb"]}, ".checklist", "multiline"),
        ("tester", {"checklist": ["a\u00adb"]}, ".checklist", "multiline"),
        ("tester", {"checklist": ["a\u2029b"]}, ".checklist", "multiline"),
        ("reviewer", {"checklist": ["x" * 301]}, ".checklist", "too_long"),
        ("reviewer", {"checklist": ["x"] * 31}, ".checklist", "too_many"),
        ("coder", {"tone": "kind"}, ".tone", "extra_forbidden"),
    ],
)
def test_the_hub_refuses_what_it_would_otherwise_drop(
    owner: flow.Human, migrated: Engine, role: str, rules_in: Any, field: str, error: str
) -> None:
    before = _version(migrated)
    response = owner.patch(BASE, {"settings": {"role_rules": {role: rules_in}}})
    assert response.headers["Maity-Error"] == "invalid"
    fields = response.json()["error"]["details"]["fields"]
    assert fields == {f"settings.role_rules.{role}{field}": error}
    assert "role_rules" not in owner.get(BASE).json()["settings"]
    assert _version(migrated) == before


@pytest.mark.parametrize("given", [{"role_rules": SET}, {"role_rules": None}])
def test_an_agent_never_writes_the_rules_it_works_under(
    owner: flow.Human, make_client: ClientFactory, given: dict[str, Any]
) -> None:
    admin = flow.agent(make_client, owner, role="admin")
    for body in ({"settings": given}, {"settings": {**given, "onboarding": None}}):
        response = admin.patch(BASE, body)
        assert response.headers["Maity-Error"] == "forbidden", response.text
        assert response.json()["error"]["details"] == {"reason": "humans_only"}
    assert "role_rules" not in owner.get(BASE).json()["settings"]


def test_a_member_human_may_not_write_them_either(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    """`role_rules` is `project:admin`'s (§6.28): a human with trust `member` is refused too."""
    member = flow.human(make_client, migrated, "member")
    with migrated.connect() as conn:
        project_id = conn.execute(select(t.project.c.id)).scalar_one()
    factory.membership(migrated, project_id, "member", human_id=member.id)
    response = member.patch(BASE, {"settings": {"role_rules": SET}})
    assert response.status_code == 403, response.text
    assert response.json()["error"]["details"]["scope"] == "project:admin"
    assert "role_rules" not in owner.get(BASE).json()["settings"]
