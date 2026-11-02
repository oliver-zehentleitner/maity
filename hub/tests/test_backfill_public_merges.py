"""The one-time backfill of `merge.public` on old ticker merges (hub/context/probe.md 6af0bb67)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine, select, update

from maity_hub import tables as t
from tests import flow
from tests.test_swarm import owner, project_id, public_prs, ticker_merge  # noqa: F401

spec = importlib.util.spec_from_file_location(
    "backfill_public_merges",
    Path(__file__).resolve().parent.parent / "scripts" / "backfill_public_merges.py",
)
assert spec is not None and spec.loader is not None
backfill: Any = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = backfill  # a dataclass looks its module up while it is made
spec.loader.exec_module(backfill)

URL = "https://github.com/maintainer/maity"


@pytest.fixture
def named(migrated: Engine, project_id: str) -> Any:  # noqa: F811
    with migrated.begin() as conn:
        conn.execute(
            update(t.project)
            .where(t.project.c.id == project_id)
            .values(repository_url=URL, repository_public=True)
        )
    return backfill.Named(project_id, "maintainer/maity", URL)


def merges(engine: Engine, project: str | None = None) -> dict[int, dict[str, Any]]:
    query = select(t.event.c.payload).where(t.event.c.kind == "ticker").order_by(t.event.c.seq)
    if project is not None:
        query = query.where(t.event.c.project_id == project)
    with engine.connect() as conn:
        rows = conn.execute(query)
        return {p["merge"]["pr"]: p["merge"] for (p,) in rows}


def test_old_merges_count_after_the_run_and_flagged_ones_stay_as_they_were(
    owner: flow.Human, migrated: Engine, project_id: str, named: Any  # noqa: F811
) -> None:
    ticker_merge(migrated, project_id, 12, [], public=None)
    ticker_merge(migrated, project_id, 13, [], public=None)
    ticker_merge(migrated, project_id, 14, [], public=False)
    ticker_merge(migrated, project_id, 15, [], public=True)
    assert public_prs(migrated, project_id) == 1
    assert backfill.run(migrated, named, change=False, undo=False, stamp="x") == 2
    assert public_prs(migrated, project_id) == 1  # counting changes nothing
    assert backfill.run(migrated, named, change=True, undo=False, stamp="2026-11-02") == 2
    assert public_prs(migrated, project_id) == 3
    found = merges(migrated)
    assert found[12] == {**found[12], "public": True, backfill.MARK: "2026-11-02"}
    assert found[14] == {"pr": 14, "merged_at": "2026-10-20T00:00:00Z", "public": False}
    assert backfill.run(migrated, named, change=True, undo=False, stamp="later") == 0


def test_undo_takes_off_exactly_what_the_run_set(
    owner: flow.Human, migrated: Engine, project_id: str, named: Any  # noqa: F811
) -> None:
    ticker_merge(migrated, project_id, 12, [], public=None)
    ticker_merge(migrated, project_id, 15, [], public=True)
    before = merges(migrated)
    backfill.run(migrated, named, change=True, undo=False, stamp="2026-11-02")
    assert backfill.run(migrated, named, change=True, undo=True, stamp="") == 1
    assert merges(migrated) == before


@pytest.mark.parametrize(
    ("change", "why"),
    [
        ({"full_name": "someone/maity"}, "not someone/maity"),
        ({"repository_url": "https://github.com/other/repo"}, "the repository is"),
        ({"project_id": "prj-missing"}, "no such project"),
    ],
)
def test_a_project_that_does_not_match_every_name_is_refused(
    owner: flow.Human, migrated: Engine, named: Any, change: dict[str, str], why: str  # noqa: F811
) -> None:
    other = backfill.Named(**{**named.__dict__, **change})
    with migrated.connect() as conn:
        assert why in backfill.refusal(conn, other)


def test_a_repository_not_found_public_is_refused_and_nothing_changes(
    owner: flow.Human, migrated: Engine, project_id: str, named: Any  # noqa: F811
) -> None:
    ticker_merge(migrated, project_id, 12, [], public=None)
    with migrated.begin() as conn:
        conn.execute(update(t.project).values(repository_public=None))
    before = merges(migrated)
    with pytest.raises(SystemExit, match="did not find it public"):
        backfill.run(migrated, named, change=True, undo=False, stamp="x")
    assert merges(migrated) == before


def test_the_script_changes_nothing_unless_every_project_matches(
    owner: flow.Human,  # noqa: F811
    migrated: Engine,
    project_id: str,  # noqa: F811
    named: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ticker_merge(migrated, project_id, 12, [], public=None)
    monkeypatch.setenv("MAITY_DATABASE_URL", migrated.url.render_as_string(hide_password=False))
    good = [named.project_id, named.full_name, URL]
    bad = [named.project_id, "someone/else", URL]
    args = ["--project", *good, "--project", *bad, "--apply"]
    assert backfill.main(args) == 2
    assert merges(migrated)[12] == {"pr": 12, "merged_at": "2026-10-20T00:00:00Z"}
    assert backfill.main(["--project", *good, "--apply"]) == 0
    assert merges(migrated)[12]["public"] is True


def test_another_project_stays_untouched_by_a_run_and_its_undo(
    owner: flow.Human, migrated: Engine, project_id: str, named: Any  # noqa: F811
) -> None:
    """The same owner, the same repository, found public, old merges of its own: only the named
    project's items change, on the run and on its undo."""
    flow.project(owner, "other")
    with migrated.begin() as conn:
        other = conn.execute(
            select(t.project.c.id).where(t.project.c.id != project_id)
        ).scalar_one()
        conn.execute(
            update(t.project)
            .where(t.project.c.id == other)
            .values(repository_url=URL, repository_public=True)
        )
    ticker_merge(migrated, project_id, 12, [], public=None)
    ticker_merge(migrated, other, 12, [], public=None)
    ticker_merge(migrated, other, 13, [], public=None)
    theirs = merges(migrated, other)
    assert backfill.run(migrated, named, change=True, undo=False, stamp="2026-11-02") == 1
    assert merges(migrated, project_id)[12]["public"] is True
    assert merges(migrated, other) == theirs
    backfill.run(migrated, backfill.Named(other, "maintainer/other", URL), change=True,
                 undo=False, stamp="2026-11-02")  # fmt: skip
    assert backfill.run(migrated, named, change=True, undo=True, stamp="") == 1
    assert "public" not in merges(migrated, project_id)[12]
    assert all(m["public"] is True for m in merges(migrated, other).values())


def test_undo_without_apply_only_counts(
    owner: flow.Human,  # noqa: F811
    migrated: Engine,
    project_id: str,  # noqa: F811
    named: Any,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    ticker_merge(migrated, project_id, 12, [], public=None)
    monkeypatch.setenv("MAITY_DATABASE_URL", migrated.url.render_as_string(hide_password=False))
    good = ["--project", named.project_id, named.full_name, URL]
    assert backfill.main([*good, "--apply"]) == 0
    marked = merges(migrated)
    assert backfill.main([*good, "--undo"]) == 0
    assert merges(migrated) == marked
    assert "would undo 1 merges" in capsys.readouterr().out
    assert backfill.main([*good, "--undo", "--apply"]) == 0
    assert "public" not in merges(migrated)[12]
    assert "undid 1 merges" in capsys.readouterr().out
