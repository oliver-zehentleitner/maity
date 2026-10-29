"""The maps the hub keeps per project in the process stay bounded (card tsk-7865c6c2gszb):
each is filled past its bound, and what it keeps is the newest written."""

from __future__ import annotations

import threading
from types import SimpleNamespace
from typing import Any

import pytest

from maity_hub import bounded, clock, forge, forge_access, images, ktw, swarm


def test_put_keeps_the_newest_written_and_what_stays() -> None:
    kept: dict[str, int] = {}
    for n in range(5):
        bounded.put(kept, f"k{n}", n, 3)
    assert list(kept) == ["k2", "k3", "k4"]
    assert bounded.put(kept, "k2", 20, 3) == []  # written again: now the newest
    assert bounded.put(kept, "k5", 5, 3) == ["k3"]
    assert list(kept) == ["k4", "k2", "k5"]
    held = {"a": True, "b": False, "c": False}
    assert bounded.put(held, "d", False, 2, stays=lambda v: v) == ["b", "c"]
    assert list(held) == ["a", "d"]  # the one held stays, past the bound if it must


def test_the_ktw_cache_keeps_the_newest_projects_and_drops_their_reads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ktw, "PROJECTS_KEPT", 2)
    monkeypatch.setattr(
        ktw.Cache, "_read", lambda _self, _r, _p, url, _last: ktw._Entry(None, ktw._now(), url)
    )
    cache = ktw.Cache()
    cache.last_good[("p0", "context/x.md")] = (SimpleNamespace(), None)  # type: ignore[assignment]
    for n in range(5):
        cache.get(forge.Forge(None), f"p{n}", None, max_age=0)
    assert list(cache.entries) == ["p3", "p4"]
    assert set(cache.locks) == {"p3", "p4"}
    assert cache.last_good == {}  # p0's last good read went with it


def test_ktw_forget_drops_the_lock_too() -> None:
    cache = ktw.Cache()
    cache._lock("p")
    cache.forget("p")
    assert cache.locks == {}


def test_the_swarm_cache_keeps_the_newest_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(swarm, "PROJECTS_KEPT", 3)
    monkeypatch.setattr(swarm, "window", lambda _conn, _p: SimpleNamespace(as_of=clock.now()))
    cache = swarm._Cache()
    for n in range(10):
        cache.get(None, f"p{n}")  # type: ignore[arg-type]
    assert list(cache._kept) == ["p7", "p8", "p9"]


def test_forge_access_keeps_the_newest_choices_and_sources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(forge_access, "CHOSEN_KEPT", 2)
    monkeypatch.setattr(forge_access, "VIA_KEPT", 3)
    monkeypatch.setattr(forge_access, "_last_via", {})
    access = forge_access.ForgeAccess(None, None, None)  # type: ignore[arg-type]
    facts = SimpleNamespace(key=lambda _base: ("same",))
    monkeypatch.setattr(access, "_facts", lambda _p: facts)
    monkeypatch.setattr(access, "_choose", lambda p, _f, _b: forge.Forge("t", project_id=p))
    for n in range(6):
        access.reader(f"p{n}", forge.Forge(None))
    assert list(access._chosen) == ["p4", "p5"]
    assert list(forge_access._last_via) == ["p3", "p4", "p5"]


def test_the_image_maps_keep_the_newest_and_never_a_gate_in_use(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(images, "KEPT", 2)
    images.reset()
    held = images._flight(("p0", "logo"))
    held.acquire()
    try:
        for n in range(1, 5):
            images._flight((f"p{n}", "logo"))
        # The held gate counts against the bound and stays; the newest fills the rest.
        assert list(images._flights) == [("p0", "logo"), ("p4", "logo")]
    finally:
        held.release()
    for n in range(5):
        images._failed((f"p{n}", "logo"))
    assert list(images._failures) == [("p3", "logo"), ("p4", "logo")]
    images.reset()


def test_a_gate_handed_out_is_the_same_until_dropped() -> None:
    images.reset()
    first: Any = images._flight(("p", "logo"))
    assert images._flight(("p", "logo")) is first
    assert isinstance(first, type(threading.Lock()))
    images.reset()
