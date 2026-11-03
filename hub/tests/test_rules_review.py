"""The review line of the generated rules (docs/api.md §6.9, "The review line"): a member whose
role is `reviewer` or counts as it reads it, every other role does not (tsk-g9kybnt9kf6b)."""

from __future__ import annotations

from typing import Any

import pytest

from maity_hub import rules


def _project(roles: list[dict[str, Any]] | None = None) -> Any:
    return type(
        "P",
        (),
        {
            "name": "p", "rules_version": 1, "state": "build", "state_note": None,
            "released_at": None, "policy_preset": "x", "claim_policy": "x", "done_authority": "x",
            "tag_authority": "x", "steward_writes": "x", "lease_seconds": 60,
            "keep_the_why": False, "rules_markdown": None, "roles": roles,
        },
    )()  # fmt: skip


@pytest.mark.parametrize("role", ["reviewer", "purple-team"])
def test_a_reviewer_and_a_role_that_counts_as_one_get_the_review_line(role: str) -> None:
    for supervised in (False, True):
        text = rules.generate(_project(), "member", role, "the owner", supervised=supervised)
        assert "## Reviewing" in text and rules.REVIEW in text


@pytest.mark.parametrize("role", ["coder", "tester", "red-team", "blue-team", "manager", "ops"])
def test_other_roles_get_no_review_line(role: str) -> None:
    text = rules.generate(_project(), "member", role, "the owner")
    assert "## Reviewing" not in text and rules.REVIEW not in text


def test_a_project_role_on_reviewer_gets_it_and_one_on_coder_does_not() -> None:
    roles = [
        {"name": "auditor", "base": "reviewer", "guide": "", "guide_by": None},
        {"name": "builder", "base": "coder", "guide": "", "guide_by": None},
    ]
    assert rules.REVIEW in rules.generate(_project(roles), "member", "auditor", "the owner")
    assert rules.REVIEW not in rules.generate(_project(roles), "member", "builder", "the owner")


def test_the_review_line_says_what_the_contract_says() -> None:
    for kept in ("fresh context", "fresh subagent", "`review_result`", "§8.4", "`Ran`"):
        assert kept in rules.REVIEW
    assert "unchanged, with no summary or rewrite" in rules.REVIEW


def test_the_review_line_sits_between_duty_and_keep_the_why() -> None:
    project = _project()
    project.keep_the_why = True
    project.rules_markdown = "owner text"
    text = rules.generate(project, "member", "reviewer", "the owner")
    order = ["## On duty", "## Reviewing", "## Keep the Why", "## Naming members", "## From"]
    assert [text.index(h) for h in order] == sorted(text.index(h) for h in order)


def test_the_digest_renders_the_reviewer_document(monkeypatch: pytest.MonkeyPatch) -> None:
    """The review line is in the digest through the rendered reviewer document, not only as a
    constant: a review line dropped from `generate` changes the digest too."""
    digest = rules.text_digest()
    monkeypatch.setattr(rules, "reviews", lambda project, role: False)
    assert rules.text_digest() != digest
