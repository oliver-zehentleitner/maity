"""The forge's budget across replicas on PostgreSQL (hub/context/replicas.md 83da2bfa). Clearing
`forge._budgets` is what another process looks like: it knows only what the row says."""

from __future__ import annotations

import time
from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any
from unittest import mock

import pytest
from sqlalchemy import Engine, select, update

from maity_hub import forge, shared_budget
from maity_hub import tables as t

SOURCE = "s" * 64
HOUR = 3600


def headers(remaining: int, reset: float, limit: int = 5000) -> dict[str, str]:
    return {
        "X-RateLimit-Limit": str(limit),
        "X-RateLimit-Remaining": str(remaining),
        "X-RateLimit-Reset": str(int(reset)),
    }


@pytest.fixture
def shared(migrated: Engine) -> Iterator[Engine]:
    if migrated.dialect.name != "postgresql":
        pytest.skip("only PostgreSQL runs replicas")
    forge._budgets.clear()
    shared_budget.configure(migrated)
    yield migrated
    shared_budget.configure(None)
    forge._budgets.clear()


def _row(engine: Engine) -> Any:
    with engine.connect() as conn:
        return conn.execute(select(t.forge_budget)).one()


def _other_pod_starts() -> None:
    forge._budgets.clear()


def test_every_other_database_keeps_the_budget_in_the_process(migrated: Engine) -> None:
    if migrated.dialect.name == "postgresql":
        pytest.skip("PostgreSQL shares it")
    shared_budget.configure(migrated)
    forge._budgets.clear()
    forge._note(SOURCE, headers(100, time.time() + HOUR), spent=False)
    with migrated.connect() as conn:
        assert conn.execute(select(t.forge_budget)).all() == []
    forge._budgets.clear()


def test_another_pod_stops_at_the_reserve_this_one_reached(shared: Engine) -> None:
    reset = time.time() + HOUR
    forge._note(SOURCE, headers(100, reset), spent=False)  # under 5 % of 5000
    _other_pod_starts()
    held = forge._take(SOURCE)
    assert held is not None and abs(held.timestamp() - int(reset)) < 1


def test_another_pods_read_counts_what_this_one_spent(shared: Engine) -> None:
    """Just above the reserve here; one read later it is under it."""
    reset = time.time() + HOUR
    forge._note(SOURCE, headers(251, reset), spent=False)
    _other_pod_starts()
    assert forge._take(SOURCE) is None
    assert forge._budgets[SOURCE].remaining == 251
    assert forge._take(SOURCE) is not None  # one in flight: 250 - 1 under the 250 kept


def test_a_hold_reaches_retry_at_on_another_pod(shared: Engine) -> None:
    token_source = forge._source("a token")
    forge._note(token_source, {"Retry-After": "120"}, spent=True)
    _other_pod_starts()
    held = forge.retry_at("a token")
    assert held is not None and 110 < held.timestamp() - time.time() <= 121


def test_within_a_window_the_lowest_remaining_counts_in_any_order(shared: Engine) -> None:
    reset = time.time() + HOUR
    forge._note(SOURCE, headers(4000, reset), spent=False)
    _other_pod_starts()
    forge._note(SOURCE, headers(4500, reset), spent=False)
    assert _row(shared).remaining == 4000


def test_a_later_window_replaces_and_an_earlier_changes_nothing(shared: Engine) -> None:
    now = time.time()
    forge._note(SOURCE, headers(4000, now + HOUR), spent=False)
    _other_pod_starts()
    forge._note(SOURCE, headers(4900, now + 2 * HOUR), spent=False)
    assert _row(shared).remaining == 4900
    _other_pod_starts()
    forge._note(SOURCE, headers(10, now + HOUR), spent=False)
    row = _row(shared)
    assert row.remaining == 4900 and row.reset == int(now + 2 * HOUR)


def test_a_new_window_opens_again_on_every_pod(shared: Engine) -> None:
    """A spent window's row says nothing any more once its reset has passed."""
    past = time.time() - 1
    forge._note(SOURCE, headers(100, past), spent=False)
    with shared.begin() as conn:
        conn.execute(update(t.forge_budget).values(until=past))
    _other_pod_starts()
    assert forge._take(SOURCE) is None


def test_a_database_that_does_not_answer_costs_the_sharing_not_the_read(
    shared: Engine,
) -> None:
    with mock.patch.object(shared, "begin", side_effect=OSError("gone")):
        assert forge._take(SOURCE) is None
        forge._note(SOURCE, headers(100, time.time() + HOUR), spent=False)
    assert forge._budgets[SOURCE].remaining == 100  # the process still knows


def test_old_sources_go(shared: Engine, monkeypatch: pytest.MonkeyPatch) -> None:
    forge._note(SOURCE, headers(4000, time.time() + HOUR), spent=False)
    with shared.begin() as conn:
        conn.execute(
            update(t.forge_budget).values(seen_at=_row(shared).seen_at - shared_budget.KEPT * 2)
        )
    monkeypatch.setattr(shared_budget, "SWEEP_EVERY", 1)
    other = "o" * 64
    forge._note(other, headers(4000, time.time() + HOUR), spent=False)
    assert [_row(shared).source] == [other]


def test_a_later_window_without_a_remaining_takes_it_as_the_row_does() -> None:
    budget = forge._Budget(remaining=7, reset=100.0)
    forge._merge(budget, SimpleNamespace(until=0.0, limit=None, remaining=None, reset=200.0))
    assert (budget.remaining, budget.reset) == (None, 200.0)
