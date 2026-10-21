"""Transient conflicts are run again; everything else surfaces at once."""

from __future__ import annotations

import pytest
from sqlalchemy.exc import OperationalError

from maity_hub.db import RETRIES, retrying


class _Deadlock(Exception):
    sqlstate = "40001"


class _Gone(Exception):
    args = (2003,)


def _failing(errors: list[Exception]) -> object:
    def work() -> str:
        if errors:
            raise OperationalError("stmt", {}, errors.pop(0))
        return "done"

    return work


def test_a_deadlock_is_run_again() -> None:
    assert retrying(_failing([_Deadlock(), _Deadlock()])) == "done"  # type: ignore[arg-type]


def test_a_lasting_deadlock_surfaces_after_the_retries() -> None:
    with pytest.raises(OperationalError):
        retrying(_failing([_Deadlock() for _ in range(RETRIES)]))  # type: ignore[arg-type]


def test_any_other_failure_surfaces_at_once() -> None:
    errors: list[Exception] = [_Gone(), _Deadlock()]
    with pytest.raises(OperationalError):
        retrying(_failing(errors))  # type: ignore[arg-type]
    assert len(errors) == 1  # not retried
