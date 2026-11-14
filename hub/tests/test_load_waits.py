"""Load that waits: a Keep the Why view's read answers within its wait, not after the read's
30 s while every permit is taken (docs/api.md §11.5), and many reads of a contract's text
ask the forge for the default branch's head once (§6.8).

Run with `pytest -m load -s` (they print their numbers); CI's hub-load job runs them too.
The clock is soft, as in tests/test_load.py: a runner is noisy, so the bound is the wait
plus a second, and the count of forge reads is the exact check."""

from __future__ import annotations

import statistics
import time
from typing import Any

import pytest

from maity_hub import contract_text, forge, ktw, ktw_reads
from tests import flow
from tests.test_contract_text import API
from tests.test_keep_the_why import BASE, Fake
from tests.test_keep_the_why_views import PATH, fake, owner, project  # noqa: F401
from tests.test_probe import SHA, TOKEN

pytestmark = pytest.mark.load

REPEATS = 5
CONTRACT_READS = 200


def test_a_views_read_with_every_permit_taken_answers_within_the_wait(
    owner: flow.Human,  # noqa: F811
    fake: Fake,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = [1000.0]
    monkeypatch.setattr(ktw, "_now", lambda: now[0])
    fake.family()
    project(owner)
    owner.get(PATH)
    taken = [ktw_reads._all.acquire(blocking=False) for _ in range(ktw_reads.IN_FLIGHT_ALL)]
    assert all(taken)
    took: list[float] = []
    try:
        for _ in range(REPEATS):
            ktw.RAW.files.pop(("state", f"{BASE}/cli/state.json"), None)  # dropped for room
            now[0] += ktw.FORCE_INTERVAL + 1  # past the hold, inside the family's max_age
            began = time.monotonic()
            answer = owner.get(f"{PATH}/export", params={"root": "cli"})
            took.append(time.monotonic() - began)
            assert answer.status_code == 503
    finally:
        for _ in taken:
            ktw_reads._all.release()
    median = statistics.median(took)
    print(f"\nviews read, every permit taken: median {median:.3f} s, max {max(took):.3f} s")
    assert max(took) < ktw.LOCK_WAIT + 1.0


def test_many_contract_reads_ask_for_the_branch_once(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def branch(_fg: forge.Forge, repository: str, name: str) -> dict[str, Any]:
        calls.append(name)
        return {"name": name, "head_sha": SHA, "found": True}

    monkeypatch.setattr(forge.Forge, "branch", branch)
    monkeypatch.setattr(forge.Forge, "file_at", lambda *_a: API.encode())
    fg = forge.Forge(TOKEN)
    began = time.monotonic()
    for _ in range(CONTRACT_READS):
        contract_text.read(fg, "acme/maity", "main", "docs/api.md", "6.2")
    took = time.monotonic() - began
    print(f"\n{CONTRACT_READS} contract reads: {len(calls)} branch reads, {took:.3f} s")
    assert len(calls) == 1
