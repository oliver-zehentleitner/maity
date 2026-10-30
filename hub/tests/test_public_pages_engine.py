"""docs/api.md §16.9: rendering pages again and taking them off, under both modes, the
sitemap and `robots.txt`. A kind of page of the test's own stands in for the real ones."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import Connection, Engine, select

from maity_hub import clock, public_pages
from maity_hub import tables as t
from maity_hub.config import Settings
from maity_hub.routes import seo
from tests.conftest import ClientFactory

NOTE = "note"


class Shown:
    """What the test kind renders: target id to (title, public, input time)."""

    def __init__(self) -> None:
        self.targets: dict[str, tuple[str, bool, datetime]] = {}
        self.renders = 0
        self.fail = False


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
            )
        ]

    def targets(conn: Connection) -> list[str]:
        return sorted(state.targets)

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
        )
    shown.targets["a"] = ("A", True, clock.now())
    public_pages.startup(migrated, config)
    assert set(rows(migrated)) == {"/a"}
    off = replace(settings, public_pages=False)
    public_pages.startup(migrated, off)  # off: nothing is rendered or deleted
    assert set(rows(migrated)) == {"/a"}


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


def test_robots_allows_everything_but_the_hubs_own_first_segments(
    make_client: ClientFactory, migrated: Engine
) -> None:
    text = make_client(public_pages=True).get("/robots.txt").text
    assert text.startswith("User-agent: *\n")
    for first in ("api", "assets", "join", "r", "mail", "badge"):
        assert f"Disallow: /{first}/\n" in text
    assert "Disallow: /\n" not in text and "impressum" not in text
    assert "Sitemap: https://hub.example/sitemap.xml" in text
    off = make_client().get("/robots.txt").text
    assert "Disallow: /\n" in off  # as before while pages are off
