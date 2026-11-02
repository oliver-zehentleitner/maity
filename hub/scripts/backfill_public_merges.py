"""One-time: mark the old merges of named projects as read publicly (hub/context/probe.md
6af0bb67). Ticker merges written before `merge.public` existed carry no flag, so a page without
sign-in does not count them. The maintainer decided that for two projects they count; this sets
`merge.public: true` and a mark on exactly those items, and `--undo` takes off exactly what it set.

    MAITY_DATABASE_URL=... python scripts/backfill_public_merges.py \\
        --project <id> <owner>/<slug> <repository url> [--project ...] [--undo] [--apply]

Without `--apply` it only counts: what it would mark or, with `--undo`, what it would take off.
A project is refused unless its id, full name and repository URL all match what is given and its
repository's last check found it public. Items that already say `public`, true or false, are
never touched.
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import Connection, Engine, select, update

from maity_hub import namespace
from maity_hub import tables as t
from maity_hub.db import make_engine
from maity_hub.events import lock_project

MARK = "public_backfill"


@dataclass(frozen=True)
class Named:
    project_id: str
    full_name: str
    repository_url: str


def refusal(conn: Connection, named: Named) -> str | None:
    project = conn.execute(select(t.project).where(t.project.c.id == named.project_id)).first()
    if project is None:
        return f"{named.project_id}: no such project"
    found = namespace.full_name(conn, project)
    if found != named.full_name:
        return f"{named.project_id} is {found}, not {named.full_name}"
    if project.repository_url != named.repository_url:
        return f"{found}: the repository is {project.repository_url}, not {named.repository_url}"
    if project.repository_public is not True:
        return f"{found}: the repository's last check did not find it public"
    return None


def _items(conn: Connection, project_id: str, undo: bool) -> list[tuple[int, dict[str, Any]]]:
    """The merges this run would change: without a flag, or for `undo` with the mark."""
    rows = conn.execute(
        select(t.event.c.seq, t.event.c.payload)
        .where(
            t.event.c.project_id == project_id,
            t.event.c.kind == "ticker",
            t.event.c.subject_type == "pull_request",
            t.event.c.redacted.is_(False),
        )
        .order_by(t.event.c.seq)
    )
    found = []
    for seq, payload in rows:
        payload = payload or {}
        merge = payload.get("merge")
        if payload.get("type") != "merge" or not isinstance(merge, dict):
            continue
        if (MARK in merge) if undo else ("public" not in merge):
            found.append((seq, payload))
    return found


def run(engine: Engine, named: Named, *, change: bool, undo: bool, stamp: str) -> int:
    """How many items the run changes (or would change); one transaction, under the lock."""
    with engine.begin() as conn:
        if change:
            lock_project(conn, named.project_id)
        why = refusal(conn, named)
        if why is not None:
            raise SystemExit(f"refused: {why}")
        items = _items(conn, named.project_id, undo)
        if not change:
            return len(items)
        for seq, payload in items:
            merge = dict(payload["merge"])
            if undo:
                merge.pop("public", None)
                merge.pop(MARK, None)
            else:
                merge["public"] = True
                merge[MARK] = stamp
            conn.execute(
                update(t.event)
                .where(t.event.c.seq == seq)
                .values(payload={**payload, "merge": merge})
            )
        return len(items)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument(
        "--project", nargs=3, action="append", required=True,
        metavar=("ID", "OWNER/SLUG", "REPOSITORY_URL"),
    )  # fmt: skip
    parser.add_argument("--undo", action="store_true", help="take off what a run marked")
    parser.add_argument("--apply", action="store_true", help="change; without it, only count")
    args = parser.parse_args(argv)
    engine = make_engine(os.environ["MAITY_DATABASE_URL"])
    named = [Named(*triple) for triple in args.project]
    with engine.connect() as conn:  # every project is checked before any is changed
        for one in named:
            why = refusal(conn, one)
            if why is not None:
                print(f"refused: {why}", file=sys.stderr)
                return 2
    verb = {
        (False, False): "would mark",
        (True, False): "marked",
        (False, True): "would undo",
        (True, True): "undid",
    }[(args.apply, args.undo)]
    for one in named:
        count = run(engine, one, change=args.apply, undo=args.undo, stamp=date.today().isoformat())
        print(f"{one.full_name}: {verb} {count} merges")
    return 0


if __name__ == "__main__":
    sys.exit(main())
