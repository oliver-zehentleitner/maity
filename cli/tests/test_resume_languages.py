"""The lines that say in which language an agent writes what (docs/api.md §5.2, §13)."""

from __future__ import annotations

from typing import Any

from maity import onboarding


def _text(**fields: Any) -> str:
    me = {
        "member_id": "agt-b",
        "handle": "agent-b",
        "owner": {"id": "hum-o", "handle": "olga", "language": "de"},
    }
    data = {
        "me": me,
        "membership": {"trust": "member", "role": "coder"},
        "project": {"slug": "p", "full_name": "o/p", "state": "active", "language": "fr"},
        **fields,
    }
    return onboarding.render(data)


def _human(member_id: str, handle: str, language: str | None) -> dict[str, Any]:
    person = {"member_id": member_id, "handle": handle, "kind": "human"}
    return {**person, "language": language} if language else person


def test_the_project_and_each_human_have_their_line() -> None:
    text = _text(
        peers=[_human("hum-k", "kim", "ja"), {"member_id": "agt-c", "handle": "c", "kind": "agent"}]
    )
    assert "Language: fr\n" in text
    assert "Write to @kim in ja\n" in text
    assert "Write to @c " not in text  # an agent has no language of its own


def test_the_own_human_outside_the_project_has_a_line_too() -> None:
    assert "Write to @olga in de\n" in _text(peers=[_human("hum-k", "kim", "ja")])


def test_the_own_human_among_the_peers_has_one_line() -> None:
    text = _text(peers=[_human("hum-o", "olga", "de")])
    assert text.count("Write to @olga in de") == 1


def test_a_missing_value_means_english() -> None:
    text = _text(
        project={"slug": "p", "full_name": "o/p", "state": "active"},
        peers=[_human("hum-k", "kim", None)],
    )
    assert "Language: en\n" in text
    assert "Write to @kim in en\n" in text
