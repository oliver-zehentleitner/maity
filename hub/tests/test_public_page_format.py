"""docs/api.md §16.9: a page rendered by an earlier version of the hub never replaces one a later
version rendered, and a page of an earlier version is rendered again. Each row's `inputs` names
the format it was rendered in (`public_pages.FORMAT`); a row without one is format 1."""

from __future__ import annotations

import hashlib

from sqlalchemy import Engine, String

from maity_hub import clock, public_pages
from maity_hub import tables as t
from maity_hub.config import Settings
from tests.test_public_pages_engine import NOTE, Shown, hub, rows, shown  # noqa: F401


def stored(engine: Engine, inputs: str, body: str = "<!doctype html><title>A</title>") -> None:
    with engine.begin() as conn:
        public_pages.put(
            conn,
            path="/a",
            kind=NOTE,
            target_id="a",
            body=body,
            inputs=inputs,
            lastmod=clock.now(),
            view="note",
            data={"title": "A"},
        )


def test_the_format_of_a_row() -> None:
    assert public_pages.format_of("f2:abc") == 2 and public_pages.format_of("f17:abc") == 17
    # Before the prefix, a digest or anything else: format 1.
    assert public_pages.format_of("abc") == 1 and public_pages.format_of("A@2026-11-15:00") == 1
    assert public_pages.stamped("abc") == f"f{public_pages.FORMAT}:abc"


def test_a_stamped_digest_fits_the_column() -> None:
    # A sha256 in hex is the column's whole width: the prefix takes its place from the end, so a
    # row stays writable where the database holds the width to its word (PostgreSQL, MariaDB).
    column = t.public_page.c.inputs.type
    assert isinstance(column, String)
    width = column.length
    assert width == public_pages.INPUTS_LENGTH
    made = public_pages.stamped(hashlib.sha256(b"inputs").hexdigest())
    assert len(made) == width and public_pages.format_of(made) == public_pages.FORMAT
    other = public_pages.stamped(hashlib.sha256(b"other inputs").hexdigest())
    assert made != other


def test_a_row_of_a_later_format_is_deleted_and_never_overwritten(
    migrated: Engine, settings: Settings, shown: Shown  # noqa: F811
) -> None:
    config = hub(settings)
    at = clock.now()
    shown.targets["a"] = ("A", True, at)
    stored(migrated, f"f{public_pages.FORMAT + 1}:later", body="<p>a later version's page</p>")
    with migrated.begin() as conn:
        public_pages.refresh(conn, config, NOTE, "a")
    # Off, not replaced: the later version renders it first, as every target without a page.
    assert rows(migrated) == {} and shown.renders == 0
    with migrated.begin() as conn:
        assert public_pages._unrendered(conn, public_pages.KINDS[NOTE]) == ["a"]


def test_a_row_of_an_earlier_format_with_the_same_inputs_is_rendered_again(
    migrated: Engine, settings: Settings, shown: Shown  # noqa: F811
) -> None:
    config = hub(settings)
    at = clock.now()
    shown.targets["a"] = ("A", True, at)
    digest = f"A@{at.isoformat()}"  # the test kind's inputs, as this version renders them
    stored(migrated, digest)  # the same inputs, data and HTML, but no prefix: format 1
    old = rows(migrated)["/a"]
    with migrated.begin() as conn:
        public_pages.refresh(conn, config, NOTE, "a")
    row = rows(migrated)["/a"]
    assert row.inputs == public_pages.stamped(digest) and shown.renders == 1
    assert row.rendered_at >= old.rendered_at and row.inputs != old.inputs
    # Once in this format, the same inputs keep the row (b7a13a49).
    before = (row.etag, row.rendered_at)
    with migrated.begin() as conn:
        public_pages.refresh(conn, config, NOTE, "a")
    again = rows(migrated)["/a"]
    assert (again.etag, again.rendered_at) == before
