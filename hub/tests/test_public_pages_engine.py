"""docs/api.md §16.9: rendering pages again and taking them off, under both modes, the
sitemap and `robots.txt`. A kind of page of the test's own stands in for the real ones."""

from __future__ import annotations

import threading
from collections.abc import Collection, Iterator
from concurrent.futures import Future
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import Connection, Engine, insert, select, update

from maity_hub import clock, db, public_pages
from maity_hub import tables as t
from maity_hub.config import Settings
from maity_hub.routes import seo
from tests.concurrency import Step, finished, waiting
from tests.conftest import ClientFactory

NOTE = "note"


def keep(ids: list[str], among: Collection[str] | None) -> list[str]:
    """`targets`'s `among`: only those of the ids, by the same rule."""
    return ids if among is None else [i for i in ids if i in among]


class Shown:
    """What the test kind renders: target id to (title, public, input time)."""

    def __init__(self) -> None:
        self.targets: dict[str, tuple[str, bool, datetime]] = {}
        self.renders = 0
        self.fail = False
        self.listed = 0  # the target ids every `targets` call returned, summed


@pytest.fixture
def shown(settings: Settings) -> Iterator[Shown]:
    state = Shown()

    def render(conn: Connection, hub: Settings, target_id: str) -> list[public_pages.Page]:
        state.renders += 1
        if state.fail:
            raise RuntimeError("a bug in a renderer")
        found = state.targets.get(target_id)
        if found is None or not found[1]:
            return []
        title, _, at = found
        return [
            public_pages.Page(
                path=f"/{target_id}",
                body=f"<!doctype html><title>{title}</title>",
                inputs=f"{title}@{at.isoformat()}",
                lastmod=at,
                view="note",
                data={"title": title},
            )
        ]

    def targets(conn: Connection, among: Collection[str] | None = None) -> list[str]:
        state.listed += len(found := keep(sorted(state.targets), among))
        return found

    saved = dict(public_pages.KINDS)
    public_pages.KINDS.clear()
    public_pages.register(public_pages.Kind(NOTE, render, targets))
    yield state
    public_pages.KINDS.clear()
    public_pages.KINDS.update(saved)
    public_pages.configure(None)


def hub(settings: Settings, **overrides: Any) -> Settings:
    config = replace(settings, public_pages=True, **overrides)
    public_pages.configure(config)
    return config


def rows(engine: Engine) -> dict[str, Any]:
    with engine.connect() as conn:
        return {r.path: r for r in conn.execute(select(t.public_page))}


def test_a_touch_renders_the_target_in_the_transaction(
    migrated: Engine, settings: Settings, shown: Shown
) -> None:
    hub(settings)
    shown.targets["a"] = ("A one", True, clock.now())
    with migrated.begin() as conn:
        public_pages.touch(conn, NOTE, "a")
    assert "A one" in rows(migrated)["/a"].body
    # a roll back takes the page with it: it was written in the caller's transaction
    shown.targets["b"] = ("B", True, clock.now())
    with pytest.raises(RuntimeError), migrated.begin() as conn:
        public_pages.touch(conn, NOTE, "b")
        raise RuntimeError
    assert set(rows(migrated)) == {"/a"}


def test_a_target_that_is_no_longer_public_is_taken_off_at_once(
    migrated: Engine, settings: Settings, shown: Shown
) -> None:
    hub(settings)
    shown.targets["a"] = ("A", True, clock.now())
    with migrated.begin() as conn:
        public_pages.touch(conn, NOTE, "a")
    shown.targets["a"] = ("A", False, clock.now())
    with migrated.begin() as conn:
        public_pages.touch(conn, NOTE, "a")
    assert rows(migrated) == {}


def test_unchanged_inputs_keep_the_row_its_etag_and_its_lastmod(
    migrated: Engine, settings: Settings, shown: Shown
) -> None:
    hub(settings)
    at = clock.now()
    shown.targets["a"] = ("A", True, at)
    with migrated.begin() as conn:
        public_pages.touch(conn, NOTE, "a")
    first = rows(migrated)["/a"]
    shown.renders = 0
    with migrated.begin() as conn:
        public_pages.touch(conn, NOTE, "a")  # a safety-net render of the same inputs
    again = rows(migrated)["/a"]
    assert shown.renders == 1
    assert (again.etag, again.lastmod, again.rendered_at) == (
        first.etag,
        first.lastmod,
        first.rendered_at,
    )
    shown.targets["a"] = ("A two", True, at + timedelta(hours=1))
    with migrated.begin() as conn:
        public_pages.touch(conn, NOTE, "a")
    changed = rows(migrated)["/a"]
    assert changed.etag != first.etag and changed.lastmod == at + timedelta(hours=1)


def test_under_interval_a_removal_is_at_once_and_an_addition_waits(
    migrated: Engine, settings: Settings, shown: Shown
) -> None:
    config = hub(settings, public_pages_render="interval")
    shown.targets["a"] = ("A", True, clock.now())
    with migrated.begin() as conn:
        public_pages.touch(conn, NOTE, "a", removal=False)
    assert rows(migrated) == {}  # a new page waits for the run
    public_pages.render_all(migrated, config)
    assert set(rows(migrated)) == {"/a"}
    shown.targets["a"] = ("A", False, clock.now())
    with migrated.begin() as conn:
        public_pages.touch(conn, NOTE, "a")  # a removal: at once
    assert rows(migrated) == {}


def test_under_on_change_every_change_renders_at_once(
    migrated: Engine, settings: Settings, shown: Shown
) -> None:
    hub(settings, public_pages_render="on_change")
    shown.targets["a"] = ("A", True, clock.now())
    with migrated.begin() as conn:
        public_pages.touch(conn, NOTE, "a", removal=False)
    assert set(rows(migrated)) == {"/a"}


def test_nothing_is_touched_while_the_instance_serves_no_pages(
    migrated: Engine, settings: Settings, shown: Shown
) -> None:
    public_pages.configure(replace(settings, public_pages=False))
    shown.targets["a"] = ("A", True, clock.now())
    with migrated.begin() as conn:
        public_pages.touch(conn, NOTE, "a")
    assert rows(migrated) == {} and shown.renders == 0


def test_a_renderer_that_fails_takes_the_pages_off_and_raises_nothing(
    migrated: Engine, settings: Settings, shown: Shown, caplog: pytest.LogCaptureFixture
) -> None:
    hub(settings)
    shown.targets["a"] = ("A", True, clock.now())
    with migrated.begin() as conn:
        public_pages.touch(conn, NOTE, "a")
    shown.fail = True
    with caplog.at_level("ERROR"), migrated.begin() as conn:
        public_pages.touch(conn, NOTE, "a")
    assert rows(migrated) == {}
    assert any("failed" in r.getMessage() for r in caplog.records)


def test_render_all_renders_what_exists_and_deletes_the_rest(
    migrated: Engine, settings: Settings, shown: Shown
) -> None:
    config = hub(settings)
    shown.targets.update({"a": ("A", True, clock.now()), "b": ("B", True, clock.now())})
    public_pages.render_all(migrated, config)
    assert set(rows(migrated)) == {"/a", "/b"}
    del shown.targets["b"]  # the target is gone altogether
    shown.targets["c"] = ("C", True, clock.now())
    public_pages.render_all(migrated, config)
    assert set(rows(migrated)) == {"/a", "/c"}


def test_the_cleanup_decides_each_candidate_with_a_keyed_read(
    migrated: Engine, settings: Settings, shown: Shown
) -> None:
    """A page whose target went is decided by a read of that one target, not of every target
    again (tsk-ay4htr4s4w88): a pass reads the whole list twice, the pass's own and the
    cleanup's, and then nothing more per candidate, however many targets there are."""
    config = hub(settings)
    live = {f"t{n:02}": ("T", True, clock.now()) for n in range(20)}
    gone = {f"g{n:02}": ("G", True, clock.now()) for n in range(10)}
    shown.targets.update({**live, **gone})
    public_pages.render_all(migrated, config)
    for target_id in gone:
        del shown.targets[target_id]
    shown.listed = 0
    public_pages.render_all(migrated, config)
    assert set(rows(migrated)) == {f"/{i}" for i in live}
    assert shown.listed == 2 * len(live), shown.listed


def test_render_all_keeps_a_page_whose_target_became_public_during_the_pass(
    migrated: Engine, settings: Settings, shown: Shown, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A target that turns public after the pass read its targets, its page committed by
    `on_change` meanwhile, keeps that page: the cleanup deletes only what is not public when
    it runs, not what was missing from the pass's own list."""
    config = hub(settings)
    shown.targets["a"] = ("A", True, clock.now())
    original = public_pages.refresh

    def refresh(conn: Connection, hub: Settings, kind: str, target_id: str, **kw: Any) -> Any:
        found = original(conn, hub, kind, target_id, **kw)
        if target_id == "a":  # meanwhile another request makes "n" public and commits it
            shown.targets["n"] = ("N", True, clock.now())
            original(conn, hub, kind, "n")
        return found

    monkeypatch.setattr(public_pages, "refresh", refresh)
    public_pages.render_all(migrated, config)
    assert set(rows(migrated)) == {"/a", "/n"}


def test_render_all_keeps_a_page_whose_target_went_off_and_on_during_the_cleanup(
    migrated: Engine, settings: Settings, shown: Shown
) -> None:
    """The interleaving of the #1509 review (fmzu, PostgreSQL under READ COMMITTED): the
    cleanup read "n"'s page, then the targets while "n" was switched off, and "n" was switched
    on again and rendered before the delete. The candidate is decided again under its lock,
    so the page of a target that is public then stays."""
    config = hub(settings)
    shown.targets["a"] = ("A", True, clock.now())
    shown.targets["n"] = ("N", True, clock.now())
    public_pages.render_all(migrated, config)
    assert set(rows(migrated)) == {"/a", "/n"}
    kind = public_pages.KINDS[NOTE]
    calls = 0

    def targets(conn: Connection, among: Collection[str] | None = None) -> list[str]:
        nonlocal calls
        calls += 1
        if calls == 2:  # the cleanup's first read: "n" is off right now
            listed = [i for i in sorted(shown.targets) if i != "n"]
            # ... and on again, its page rendered and committed, before the delete
            public_pages.refresh(conn, config, NOTE, "n")
            return keep(listed, among)
        return keep(sorted(shown.targets), among)

    # Straight into the registry: the `shown` fixture restores it, and a monkeypatch undone
    # after that fixture would put the test kind back for the tests that follow.
    public_pages.KINDS[NOTE] = replace(kind, targets=targets)
    public_pages.render_all(migrated, config)
    assert set(rows(migrated)) == {"/a", "/n"}


def test_on_postgresql_the_cleanup_spares_a_page_rendered_by_another_transaction(
    migrated: Engine, settings: Settings, shown: Shown
) -> None:
    """The same interleaving with two real transactions (PostgreSQL, READ COMMITTED): "n" is
    rendered and committed by another connection after the cleanup's first read of the
    targets, so the cleanup keeps its page; and a render that comes while the cleanup holds
    "n"'s lock waits for it, so it cannot fall between the second read and the delete."""
    if migrated.dialect.name != "postgresql":
        pytest.skip("SQLite writes one transaction at a time; the window is PostgreSQL's")
    config = hub(settings)
    shown.targets["a"] = ("A", True, clock.now())
    shown.targets["n"] = ("N", True, clock.now())
    public_pages.render_all(migrated, config)
    kind = public_pages.KINDS[NOTE]
    calls = 0
    late: list[Step] = []

    def render_n() -> None:
        with migrated.begin() as other:
            public_pages.refresh(other, config, NOTE, "n", fresh=True)

    def targets(conn: Connection, among: Collection[str] | None = None) -> list[str]:
        nonlocal calls
        calls += 1
        if calls == 2:  # off at this read, then on again and rendered by another request
            render_n()
            return keep([i for i in sorted(shown.targets) if i != "n"], among)
        if calls == 3:  # the cleanup holds "n"'s lock: another render of "n" waits for it
            started, future = threading.Event(), Future[None]()

            def step() -> None:
                started.set()
                try:
                    render_n()
                    future.set_result(None)
                except BaseException as error:
                    future.set_exception(error)

            threading.Thread(target=step, daemon=True).start()
            late.append(Step(future, started, conn))
            assert waiting(late[0])
        return keep(sorted(shown.targets), among)

    # Straight into the registry: the `shown` fixture restores it, and a monkeypatch undone
    # after that fixture would put the test kind back for the tests that follow.
    public_pages.KINDS[NOTE] = replace(kind, targets=targets)
    public_pages.render_all(migrated, config)
    assert set(rows(migrated)) == {"/a", "/n"}
    assert len(late) == 1, "the cleanup read the targets again under the lock"
    finished(late[0])
    assert set(rows(migrated)) == {"/a", "/n"}


def test_on_postgresql_the_cleanup_holds_one_targets_lock_at_a_time(
    migrated: Engine, settings: Settings, shown: Shown, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A writer may take several targets' locks in an order of its own across its transaction
    (an organisation's suspension touches its projects one after the other, each with its
    cards: the #1509 review, fmzu). Here one holds "y" and then waits for "x" while the cleanup
    holds "x": had the cleanup kept "x" and gone on to "y", the two would wait for each other
    and PostgreSQL would end one. With one lock per candidate, both finish."""
    if migrated.dialect.name != "postgresql":
        pytest.skip("SQLite writes one transaction at a time; advisory locks are PostgreSQL's")
    config = hub(settings)
    shown.targets.update({t: (t.upper(), True, clock.now()) for t in ("a", "x", "y")})
    public_pages.render_all(migrated, config)
    del shown.targets["x"], shown.targets["y"]  # gone, their pages left: both are candidates
    original = db.xact_lock
    holds_y = threading.Event()
    writer: list[Future[None]] = []

    def other_writer() -> None:
        with migrated.begin() as conn:
            original(conn, f"public_page:{NOTE}:y")
            holds_y.set()
            original(conn, f"public_page:{NOTE}:x")

    def xact_lock(conn: Connection, name: str) -> None:
        original(conn, name)
        if name == f"public_page:{NOTE}:x" and not writer:
            future = Future[None]()

            def step() -> None:
                try:
                    other_writer()
                    future.set_result(None)
                except BaseException as error:
                    future.set_exception(error)

            writer.append(future)
            threading.Thread(target=step, daemon=True).start()
            assert holds_y.wait(10)

    monkeypatch.setattr(public_pages, "xact_lock", xact_lock)
    public_pages.render_all(migrated, config)
    writer[0].result(timeout=10)  # not ended as a deadlock's victim
    assert set(rows(migrated)) == {"/a"}


def test_startup_renders_every_page_again_before_any_is_served(
    migrated: Engine, settings: Settings, shown: Shown
) -> None:
    config = hub(settings)
    with migrated.begin() as conn:  # a page made under an earlier state
        public_pages.put(
            conn,
            path="/stale",
            kind=NOTE,
            target_id="stale",
            body="old",
            inputs="x",
            lastmod=clock.now(),
            view="note",
            data={},
        )
    shown.targets["a"] = ("A", True, clock.now())
    public_pages.startup(migrated, config)
    assert set(rows(migrated)) == {"/a"}
    off = replace(settings, public_pages=False)
    public_pages.startup(migrated, off)  # off: nothing is rendered or deleted
    assert set(rows(migrated)) == {"/a"}


def test_startup_replaces_a_page_in_place_and_never_clears_first(
    migrated: Engine, settings: Settings, shown: Shown, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A sibling process or pod keeps serving while one starts: each page is replaced where it
    stands, so a read finds the old page or the new one, never none. Same inputs with other
    HTML (a new version) is replaced; same inputs and same HTML keeps its ETag."""
    config = hub(settings)
    at = clock.now()
    shown.targets["a"] = ("A", True, at)
    shown.targets["b"] = ("B", True, at)
    public_pages.render_all(migrated, config)
    with migrated.begin() as conn:  # rendered by an earlier version from the same inputs
        conn.execute(
            update(t.public_page).where(t.public_page.c.path == "/b").values(body="old", etag="e")
        )
        conn.execute(
            insert(t.public_page).values(
                path="/gone-kind", kind="retired", target_id="x", body="x", etag="x",
                inputs="x", lastmod=at, rendered_at=at, view=None, data=None,
            )
        )  # fmt: skip
    kept = rows(migrated)["/a"].etag
    seen: list[set[str]] = []
    real = public_pages.refresh

    def watching(conn: Connection, *args: Any, **kwargs: Any) -> None:
        # Before each page's render: what is committed then, all another process could read.
        seen.append(set(conn.execute(select(t.public_page.c.path)).scalars()))
        real(conn, *args, **kwargs)

    monkeypatch.setattr(public_pages, "refresh", watching)
    public_pages.startup(migrated, config)
    assert all({"/a", "/b"} <= paths for paths in seen), seen
    after = rows(migrated)
    assert set(after) == {"/a", "/b"}
    assert after["/a"].etag == kept and after["/b"].body != "old"


def test_the_worker_renders_again_on_its_interval(
    migrated: Engine, settings: Settings, shown: Shown
) -> None:
    config = hub(settings)
    shown.targets["a"] = ("A", True, clock.now())
    worker = public_pages.Worker(migrated, config, interval=0.05)
    worker.start()
    try:
        for _ in range(100):
            if rows(migrated):
                break
            import time

            time.sleep(0.05)
    finally:
        worker.stop()
    assert set(rows(migrated)) == {"/a"}


def test_the_worker_does_not_start_while_pages_are_off(
    migrated: Engine, settings: Settings
) -> None:
    worker = public_pages.Worker(migrated, replace(settings, public_pages=False), interval=0.01)
    worker.start()
    assert worker._thread is None
    worker.stop()


# --- the sitemap and robots.txt --------------------------------------------------------------


def stored(engine: Engine, *paths: str, lastmod: datetime | None = None) -> None:
    with engine.begin() as conn:
        for path in paths:
            public_pages.put(
                conn,
                path=path,
                kind=NOTE,
                target_id=path,
                body="x",
                inputs="x",
                lastmod=lastmod or datetime(2026, 10, 30, 12, 0, 0, tzinfo=UTC),
                view="note",
                data={},
            )


def test_the_sitemap_lists_every_page_with_the_lastmod_of_its_inputs(
    make_client: ClientFactory, migrated: Engine
) -> None:
    client = make_client(public_pages=True)
    stored(migrated, "/oz-team", "/oz-team/shop")
    got = client.get("/sitemap.xml")
    assert got.status_code == 200
    assert "<loc>https://hub.example/oz-team</loc>" in got.text
    assert "<loc>https://hub.example/oz-team/shop</loc>" in got.text
    assert got.text.count("<lastmod>2026-10-30T12:00:00Z</lastmod>") == 2
    assert got.headers["cache-control"] == "public, max-age=3600"


def test_without_the_switch_the_sitemap_lists_no_page(
    make_client: ClientFactory, migrated: Engine
) -> None:
    stored(migrated, "/oz-team")
    assert make_client().get("/sitemap.xml").status_code == 404


def test_a_sitemap_over_the_limit_is_an_index_and_its_parts(
    make_client: ClientFactory, migrated: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(seo, "MAX_URLS", 2)
    client = make_client(public_pages=True)
    stored(migrated, "/a", "/b", "/c", "/d", "/e")
    index = client.get("/sitemap.xml")
    assert "<sitemapindex" in index.text
    assert index.text.count("<sitemap>") == 3
    assert "<loc>https://hub.example/sitemap-1.xml</loc>" in index.text
    first, last = client.get("/sitemap-1.xml"), client.get("/sitemap-3.xml")
    assert first.text.count("<url>") == 2 and "<loc>https://hub.example/a</loc>" in first.text
    assert last.text.count("<url>") == 1 and "<loc>https://hub.example/e</loc>" in last.text
    assert client.get("/sitemap-4.xml").status_code == 404
    assert client.get("/sitemap-0.xml").status_code == 404


def test_a_sitemap_over_the_size_limit_splits_by_bytes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(seo, "MAX_BYTES", 80)
    entries = [seo._url("https://h", f"/p{n}", None) for n in range(3)]
    assert [len(part) for part in seo.chunks(entries)] == [1, 1, 1]
    assert seo.chunks([]) == []


def test_a_sitemap_that_fits_in_one_file_has_no_parts(
    make_client: ClientFactory, migrated: Engine
) -> None:
    client = make_client(public_pages=True)
    stored(migrated, "/a")
    assert "<urlset" in client.get("/sitemap.xml").text
    assert client.get("/sitemap-1.xml").status_code == 404


def test_robots_closes_the_reserved_first_segments_and_nothing_else(
    make_client: ClientFactory, migrated: Engine
) -> None:
    from maity_hub import legal, paths

    client = make_client(public_pages=True)
    stored(migrated, "/oz-team")
    text = client.get("/robots.txt").text
    assert text.startswith("User-agent: *\n")
    for first in sorted((paths.RESERVED_FIRST | paths.HUB_FIRST) - set(legal.ADDRESS.values())):
        assert f"Disallow: /{first}/\n" in text and f"Disallow: /{first}$\n" in text, first
    for legal_page in legal.ADDRESS.values():  # the legal pages stay open
        assert f"/{legal_page}" not in text
    assert "Disallow: /\n" not in text and "Disallow: /login-help" not in text
    assert text.index("Allow: /\n") > text.rindex(
        "Disallow:"
    )  # the contract's format: then `Allow: /`
    assert text.endswith("\nSitemap: https://hub.example/sitemap.xml\n")
    off = make_client().get("/robots.txt").text
    assert "Disallow: /\n" in off  # as before while pages are off


def test_robots_names_the_sitemap_only_while_it_lists_a_url(
    make_client: ClientFactory, migrated: Engine
) -> None:
    client = make_client(public_pages=True)
    assert client.get("/sitemap.xml").status_code == 404
    assert "Sitemap:" not in client.get("/robots.txt").text
    stored(migrated, "/oz-team")
    assert client.get("/sitemap.xml").status_code == 200
    assert "Sitemap:" in client.get("/robots.txt").text


def test_a_part_of_the_sitemap_is_cached_like_the_sitemap_and_unknown_names_are_not_found(
    make_client: ClientFactory, migrated: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(seo, "MAX_URLS", 1)
    client = make_client(public_pages=True)
    stored(migrated, "/a", "/b")
    part = client.get("/sitemap-1.xml")
    assert part.status_code == 200
    assert part.headers["cache-control"] == "public, max-age=3600"
    for name in (
        "/sitemap-abc.xml",
        "/sitemap-1x.xml",
        "/sitemap--1.xml",
        "/sitemap-3.xml",
        "/sitemap-01.xml",
    ):
        assert client.get(name).status_code == 404, name
    # a path that is no sitemap part at all names nothing: the app shell
    assert "dashboard" in client.get("/sitemap-.xml").text


def test_the_join_host_has_no_sitemap_part_either(
    make_client: ClientFactory, migrated: Engine
) -> None:
    client = make_client(
        base_url="https://join.example", public_pages=True, join_url="https://join.example"
    )
    for name in ("/robots.txt", "/sitemap.xml", "/sitemap-1.xml"):
        got = client.get(name, follow_redirects=False)
        assert got.status_code == 404, name


def test_the_urlset_wrapper_counts_against_the_byte_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    entry = seo._url("https://h", "/p", None)
    wrapper = len(seo.urlset([]).encode())
    monkeypatch.setattr(seo, "MAX_BYTES", wrapper + len(entry.encode()))
    assert [len(part) for part in seo.chunks([entry, entry])] == [1, 1]
    monkeypatch.setattr(seo, "MAX_BYTES", wrapper + 2 * len(entry.encode()))
    parts = seo.chunks([entry, entry])
    assert [len(part) for part in parts] == [2]
    assert len(seo.urlset(parts[0]).encode()) <= seo.MAX_BYTES
