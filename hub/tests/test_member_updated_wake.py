"""Who `member_updated` wakes, and the merge ticker's holding instance (docs/api.md §8.2, §17.3)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from maity_hub import events, ticker, ticker_read


def _row(payload: dict[str, Any], audience: list[str], kind: str = "member_updated") -> Any:
    return SimpleNamespace(
        kind=kind,
        payload=payload,
        audience=audience,
        actor_membership=None,
        actor_credential_id=None,
        conversation_id=None,
        seq=1,
        wakes=None,
        redacted=False,
    )


def _member(agent_id: str = "agt-x", trust: str = "member") -> Any:
    return SimpleNamespace(
        id=7, agent_id=agent_id, trust=trust, role="coder", role_base="coder", isolated_since=None
    )


AUDIENCE = ["all", "member:agt-a", "trust:admin"]


def test_a_change_wakes_the_member_and_the_coordinators_and_nobody_else() -> None:
    row = _row({"id": "agt-a", "changed": ["bridges"]}, AUDIENCE)
    assert events.wakes(row, _member(), "agt-x", "i1") is False
    assert events.wakes(row, _member("agt-a"), "agt-a", "i1") is True
    assert events.wakes(row, _member("agt-l", "admin"), "agt-l", "i1") is True


@pytest.mark.parametrize(
    "payload",
    [
        {"id": "agt-a", "changed": ["reports_to"]},
        {"id": "agt-a", "changed": ["areas", "owner_id"]},
        {"id": "agt-a", "removed_at": "2026-11-01T12:00:00Z"},
    ],
)
def test_what_addressing_depends_on_wakes_everyone(payload: dict[str, Any]) -> None:
    assert events.wakes(_row(payload, AUDIENCE), _member(), "agt-x", "i1") is True


def test_other_broadcast_kinds_still_wake_through_all() -> None:
    assert events.wakes(_row({}, ["all"], "state_changed"), _member(), "agt-x", "i1") is True


def test_a_supervised_session_is_not_woken_by_a_change_of_someone_else() -> None:
    row = _row({"id": "agt-a", "changed": ["reports_to"]}, AUDIENCE)
    assert events.wakes(row, _member(), "agt-x", "i1", supervised=True) is False


def _reasons(entry: ticker.Entry) -> dict[str, Any]:
    return {
        "member_id": "agt-a",
        "why": entry.why,
        "wake": True,
        **ticker._holding_instances(entry),
    }


def _ticker(reason: dict[str, Any]) -> Any:
    return _row({"reasons": [reason]}, ["all"], "ticker")


def test_a_merge_wakes_a_holder_at_the_holding_instance_only() -> None:
    entry = ticker.Entry(why=["card_holder:tsk-1"], holding={"i1"})
    row = _ticker(_reasons(entry))
    assert ticker_read.wakes(row, "agt-a", "i1") is True
    assert ticker_read.wakes(row, "agt-a", "i2") is False
    assert ticker_read.wakes(row, "agt-a") is True  # a reader without an instance


def test_a_member_also_named_for_another_reason_is_woken_by_its_rule() -> None:
    entry = ticker.Entry(why=["card_holder:tsk-1", "area_owner:hub/"], holding={"i1"})
    assert ticker_read.wakes(_ticker(_reasons(entry)), "agt-a", "i2") is True
