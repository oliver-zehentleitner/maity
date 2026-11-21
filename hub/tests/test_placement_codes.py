"""The closed lists of reported state (docs/api.md §15.7): the hub's `REASONS` and `DETAILS`
are the contract's two tables, and every pair the tables name is a report the hub takes."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest

from maity_hub import placements as pl
from maity_hub.errors import ApiError
from maity_hub.routes.runner import Status, _check_codes

# Written as "docs" / "api.md", so that the hub-contract job of CI finds this file (ci.yml).
CONTRACT = Path(__file__).parents[2] / "docs" / "api.md"

CODE = r"`[a-z][a-z0-9_]*`"
CODES = re.compile(rf"{CODE}(?:, {CODE})*")
TARGET = re.compile(r"`([a-z][a-z0-9_]*)`(?:[:;]? .+)?")
REASON_HEADER = "| `reason` | `state` | When |"
DETAIL_HEADER = "| `detail` | With |"


def _section() -> str:
    text = CONTRACT.read_text(encoding="utf-8")
    start = text.index("\n### 15.7 Reported state\n")
    return text[start : text.index("\n### 15.8 ", start)]


def _table(header: str, columns: int) -> list[list[str]]:
    """The rows under `header`, each as its stripped cells; a row of another shape fails."""
    lines = _section().splitlines()
    at = [i for i, line in enumerate(lines) if line == header]
    assert len(at) == 1, f"§15.7 has the table {header!r} once"
    assert lines[at[0] + 1] == "|" + "---|" * columns, "the header is followed by its rule"
    rows = []
    for line in lines[at[0] + 2 :]:
        if not line.startswith("|"):
            break
        assert line.endswith("|"), line
        cells = [cell.strip() for cell in line[1:-1].split("|")]
        assert len(cells) == columns and all(cells), f"unexpected row shape: {line}"
        rows.append(cells)
    return rows


def _codes(cell: str) -> list[str]:
    return re.findall(r"`([^`]+)`", cell)


def _reasons() -> dict[str, frozenset[str]]:
    reasons: dict[str, frozenset[str]] = {}
    for codes, states, _when in _table(REASON_HEADER, 3):
        assert CODES.fullmatch(codes), f"reason cell is not a list of codes: {codes}"
        assert CODES.fullmatch(states), f"state cell is not a list of codes: {states}"
        for reason in _codes(codes):
            assert reason not in reasons, f"{reason} is listed twice"
            reasons[reason] = frozenset(_codes(states))
    return reasons


REASONS = _reasons()


def _details() -> tuple[dict[str, tuple[str, str]], set[str]]:
    """The detail table: {detail: (kind, target)} outside `join_failed`, and the codes the
    `join_failed` rows name (they are examples of any hub error code, not a closed list)."""
    details: dict[str, tuple[str, str]] = {}
    joins: set[str] = set()
    for codes, with_ in _table(DETAIL_HEADER, 2):
        match = TARGET.fullmatch(with_)
        assert match, f"the With cell does not start with one code: {with_}"
        target = match[1]
        if target == "join_failed":
            joins.update(_codes(codes))
            continue
        assert CODES.fullmatch(codes), f"detail cell is not a list of codes: {codes}"
        kind = "reason" if target in REASONS else "state"
        assert kind == "reason" or target in pl.STATES, f"{target} is no reason and no state"
        for detail in _codes(codes):
            assert detail not in details, f"{detail} is listed twice"
            details[detail] = (kind, target)
    return details, joins


DETAILS, JOIN_CODES = _details()


def test_the_contracts_tables_are_read() -> None:
    """Guards the comparisons and the parametrizations below against a parse that finds
    nothing or a part only."""
    assert len(REASONS) >= 24
    assert {"capacity", "join_failed", "orphaned"} <= set(REASONS)
    assert len(DETAILS) >= 18
    assert {"binary_not_found", "not_a_plain_clone", "target_unknown"} <= set(DETAILS)
    assert len(JOIN_CODES) >= 10
    assert {"credential_missing", "network", "pickup_used"} <= JOIN_CODES


def test_the_reasons_are_the_contracts() -> None:
    hub = {reason: frozenset(states) for reason, states in pl.REASONS.items()}
    assert hub == REASONS


def test_the_details_are_the_contracts() -> None:
    hub = {d: rule for d, rule in pl.DETAILS.items() if rule != ("reason", "join_failed")}
    assert hub == DETAILS


def test_the_join_details_are_named_by_the_contract() -> None:
    assert all(pl.JOIN_DETAIL_CODE.fullmatch(code) for code in JOIN_CODES)
    assert set(pl._JOIN_DETAILS) <= JOIN_CODES
    joined = {d for d, rule in pl.DETAILS.items() if rule == ("reason", "join_failed")}
    assert joined == set(pl._JOIN_DETAILS)


def _status(**body: Any) -> Status:
    return Status.model_validate(
        {
            "seq": 1,
            "observed_generation": 1,
            "restarts": 0,
            "target": "local",
            "since": "2026-10-22T13:00:00Z",
            **body,
        }
    )


def _report(state: str, reason: str | None, detail: str | None = None) -> Status:
    extra: dict[str, Any] = {}
    if state == "rate_limited":
        extra["retry_at"] = "2026-10-22T13:15:00Z"
    return _status(state=state, reason=reason, detail=detail, **extra)


@pytest.mark.parametrize(
    ("reason", "state"),
    sorted((reason, state) for reason, states in REASONS.items() for state in states),
)
def test_every_reason_is_taken_with_its_states(reason: str, state: str) -> None:
    _check_codes(_report(state, reason))


@pytest.mark.parametrize(
    ("detail", "kind", "target"), sorted((d, *rule) for d, rule in DETAILS.items())
)
def test_every_detail_is_taken_with_its_reason_or_state(
    detail: str, kind: str, target: str
) -> None:
    if kind == "reason":
        report = _report(sorted(REASONS[target])[0], target, detail)
    else:
        report = _report(target, "capacity" if target == "pending" else None, detail)
    _check_codes(report)


@pytest.mark.parametrize("detail", ["target_unknown", "mode_unsupported"])
def test_a_harness_refused_detail_goes_with_harness_refused_only(detail: str) -> None:
    with pytest.raises(ApiError) as refused:
        _check_codes(_report("failed", "harness_missing", detail))
    assert refused.value.details == {"fields": {"detail": "not_with_reason"}}


def test_harness_refused_without_a_detail_is_taken() -> None:
    """A runner that knows a refusal the hub does not yet name reports the reason with detail
    `null`; that report is valid (the cli CI job runs the runner's own guard without the hub)."""
    _check_codes(_report("failed", "harness_refused", None))


def test_codex_host_too_old_is_taken_with_harness_refused() -> None:
    """The Codex old-host refusal of the runner (docs/api.md §15.7, `codex_host_too_old`)."""
    _check_codes(_report("failed", "harness_refused", "codex_host_too_old"))


@pytest.mark.parametrize(
    "reason",
    # `join_failed` takes any hub error code as its detail (§15.7), so it is no other reason here.
    sorted(r for r in REASONS if r not in ("harness_refused", "join_failed")),
)
def test_codex_host_too_old_goes_with_harness_refused_only(reason: str) -> None:
    with pytest.raises(ApiError) as refused:
        _check_codes(_report(sorted(REASONS[reason])[0], reason, "codex_host_too_old"))
    assert refused.value.details == {"fields": {"detail": "not_with_reason"}}
