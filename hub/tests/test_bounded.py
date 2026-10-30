"""The maps the hub keeps per project in the process stay bounded (card tsk-7865c6c2gszb):
each is filled past its bound, and what it keeps is the newest written."""

from __future__ import annotations

import threading
from collections import OrderedDict
from types import SimpleNamespace
from typing import Any

import pytest

from maity_hub import bounded, clock, forge, forge_access, images, ktw, swarm


def test_put_keeps_the_newest_written_and_what_stays() -> None:
    kept: OrderedDict[str, int] = OrderedDict()
    for n in range(5):
        bounded.put(kept, f"k{n}", n, 3)
    assert list(kept) == ["k2", "k3", "k4"]
    assert bounded.put(kept, "k2", 20, 3) == []  # written again: now the newest
    assert bounded.put(kept, "k5", 5, 3) == ["k3"]
    assert list(kept) == ["k4", "k2", "k5"]
    held = OrderedDict([("a", 0), ("b", 0), ("c", 0)])
    assert bounded.put(held, "d", 0, 2, stays=lambda key: key == "a") == ["b", "c"]
    assert list(held) == ["a", "d"]  # the one in use stays, past the bound if it must


def test_a_key_written_again_is_never_missing_in_between() -> None:
    """A reader without the lock: the key is written in place and moved, never popped."""

    class NoPop(OrderedDict[str, int]):
        def pop(self, *args: Any) -> Any:
            raise AssertionError("popped")

        def __delitem__(self, key: str) -> None:
            raise AssertionError(f"deleted {key}")

    kept = NoPop([("a", 1), ("b", 2)])
    bounded.put(kept, "a", 10, 2)
    assert list(kept.items()) == [("b", 2), ("a", 10)]


def test_the_ktw_cache_keeps_the_newest_projects_and_drops_their_reads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ktw, "PROJECTS_KEPT", 2)
    monkeypatch.setattr(
        ktw.Cache, "_read", lambda _self, _r, _p, url, _last: ktw._Entry(None, ktw._now(), url)
    )
    cache = ktw.Cache()
    cache.last_good[("p0", "a/b", "context/x.md")] = (SimpleNamespace(), None)  # type: ignore[assignment]
    for n in range(5):
        cache.get(forge.Forge(None), f"p{n}", None, max_age=0)
    assert list(cache.entries) == ["p3", "p4"]
    assert set(cache.locks) == {"p3", "p4"}
    assert cache.last_good == {}  # p0's last good read went with it
    assert cache.users == {}  # every request left


def test_a_ktw_project_in_use_is_never_dropped(monkeypatch: pytest.MonkeyPatch) -> None:
    """A read of p0 in progress (up to FAMILY_DEADLINE): other projects filling the cache
    neither drop p0's answer nor its last good reads nor its lock."""
    monkeypatch.setattr(ktw, "PROJECTS_KEPT", 2)
    monkeypatch.setattr(
        ktw.Cache, "_read", lambda _self, _r, _p, url, _last: ktw._Entry(None, ktw._now(), url)
    )
    cache = ktw.Cache()
    cache.get(forge.Forge(None), "p0", None, max_age=0)
    cache.last_good[("p0", "a/b", "context/x.md")] = (SimpleNamespace(), None)  # type: ignore[assignment]
    lock = cache._enter("p0")  # a request of p0 between taking its lock and leaving
    for n in range(1, 5):
        cache.get(forge.Forge(None), f"p{n}", None, max_age=0)
    assert "p0" in cache.entries and ("p0", "a/b", "context/x.md") in cache.last_good
    assert cache.locks["p0"] is lock
    cache._leave("p0")
    cache.get(forge.Forge(None), "p5", None, max_age=0)
    assert "p0" not in cache.entries and "p0" not in cache.locks


def test_ktw_forget_drops_the_lock_too() -> None:
    cache = ktw.Cache()
    cache._lock("p")
    cache.forget("p")
    assert cache.locks == {}


def test_ktw_forget_drops_the_reads_even_of_a_project_in_use() -> None:
    """A changed repository: the old one's last good reads must not stand in for the new
    one's members of the same path, even while a request is in `get`; the lock stays."""
    cache = ktw.Cache()
    cache.entries["p"] = ktw._Entry(None, ktw._now(), "https://github.com/a/old")
    cache.last_good[("p", "a/old", "context/")] = (SimpleNamespace(), None)  # type: ignore[assignment]
    lock = cache._enter("p")
    cache.forget("p")
    assert "p" not in cache.entries and cache.last_good == {}
    assert cache.locks["p"] is lock
    cache._leave("p")


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
    monkeypatch.setattr(forge_access, "_last_via", OrderedDict())
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
    with images._flight(("p0", "logo")):
        for n in range(1, 5):
            with images._flight((f"p{n}", "logo")):
                pass
        # The gate in use counts against the bound and stays; the newest fills the rest.
        assert list(images._flights) == [("p0", "logo"), ("p4", "logo")]
    assert images._flying == {}
    for n in range(5):
        images._failed((f"p{n}", "logo"))
    assert list(images._failures) == [("p3", "logo"), ("p4", "logo")]
    images.reset()


def test_a_gate_asked_for_is_kept_before_it_is_taken(monkeypatch: pytest.MonkeyPatch) -> None:
    """The window of the review: a request has asked for the gate of p0 but not yet
    taken it, and other keys fill the map. It is still the same gate, so a second
    request for p0 waits for the first instead of reading the forge again."""
    monkeypatch.setattr(images, "KEPT", 1)
    images.reset()
    asked = threading.Event()
    go_on = threading.Event()
    order: list[str] = []

    def first() -> None:
        flight = images._flight(("p0", "logo"))
        flight.__enter__()  # counted, then holding the gate
        asked.set()
        go_on.wait(5)
        order.append("first")
        flight.__exit__(None, None, None)

    thread = threading.Thread(target=first)
    thread.start()
    assert asked.wait(5)
    for n in range(1, 4):
        with images._flight((f"p{n}", "logo")):
            pass
    assert ("p0", "logo") in images._flights

    def second() -> None:
        with images._flight(("p0", "logo")):
            order.append("second")

    other = threading.Thread(target=second)
    other.start()
    other.join(0.2)
    assert order == []  # waits for the first, on the same gate
    go_on.set()
    thread.join(5)
    other.join(5)
    assert order == ["first", "second"]
    images.reset()
