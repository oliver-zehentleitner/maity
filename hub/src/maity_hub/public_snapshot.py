"""What is happening in a public project, as a snapshot on its page (docs/api.md §16.9,
"A project's page"): the recent ticker entries a visitor may read, and who is online.

The maintainer's decision of 2026-11-02: visitors get no live connection. The page is
rendered with the project's other inputs, and again every `public_pages_snapshot_minutes`
by `Worker`, so the visitor's own reload shows what changed. Each ticker entry is decided
here by the card page's rule: a merge only from a repository the hub last saw public and
only when every linked card would have a page of its own, a decision only on such a card;
every other type (deploys, releases, notes, renames, jour fixe reports) never. Who is online
is named as the Board names a holder (hub/context/public-pages.md).
"""

from __future__ import annotations

import logging
import threading
from datetime import timedelta
from html import escape
from typing import Any

from sqlalchemy import Connection, Engine, select

from maity_hub import clock, moderation, public_pages, worker_runs
from maity_hub import tables as t
from maity_hub.config import Settings

log = logging.getLogger(__name__)

TICKER_LIMIT = 20  # entries on the page
TICKER_DAYS = 7  # how far back the page looks
SCAN = 200  # ticker events read at most to find them


def _card_public(conn: Connection, project_id: str, card_id: Any) -> bool:
    """Whether the card would have a page of its own (§16.9, "A card's page")."""
    from maity_hub.public_cards import shown

    if not isinstance(card_id, str):
        return False
    card = conn.execute(select(t.card).where(t.card.c.id == card_id)).first()
    return (
        card is not None
        and card.project_id == project_id
        and shown(card)
        and moderation.hold(conn, "card", card.id) is None
    )


def _entry(conn: Connection, project: Any, payload: dict[str, Any]) -> bool:
    kind = payload.get("type")
    if kind == "merge":
        merge = payload.get("merge") or {}
        return (
            project.repository_public is True
            and merge.get("public") is True
            and all(_card_public(conn, project.id, c) for c in payload.get("tasks") or [])
        )
    if kind == "decision":
        request = payload.get("request") or {}
        return _card_public(conn, project.id, request.get("task_id"))
    return False


def ticker(conn: Connection, project: Any) -> list[dict[str, Any]]:
    """The newest entries a visitor may read, newest first: `type`, `text`, `url` (a merge's
    pull request only) and `at`; never the audience, paths or request."""
    e = t.event.c
    rows = conn.execute(
        select(e.at, e.payload)
        .where(
            e.project_id == project.id,
            e.kind == "ticker",
            e.redacted.is_(False),
            e.at >= clock.now() - timedelta(days=TICKER_DAYS),
        )
        .order_by(e.seq.desc())
        .limit(SCAN)
    ).all()
    found: list[dict[str, Any]] = []
    for row in rows:
        payload = row.payload or {}
        if not _entry(conn, project, payload):
            continue
        url = payload.get("url")
        found.append(
            {
                "type": payload["type"],
                "text": str(payload.get("text") or ""),
                "url": (
                    url
                    if payload["type"] == "merge"
                    and isinstance(url, str)
                    and url.startswith("https://")
                    else None
                ),
                "at": clock.rfc3339(row.at),
            }
        )
        if len(found) == TICKER_LIMIT:
            break
    return found


def online(conn: Connection, project_id: str) -> dict[str, Any]:
    """Who is online at the snapshot: the counts per kind, and those the page names; a
    person whose `public_presence` is off is neither named nor counted (§16.9)."""
    from maity_hub.availability import presences_of
    from maity_hub.public_project_views import _shown, members

    who = members(conn, project_id)
    m = t.membership.c
    rows = conn.execute(select(t.membership).where(m.id.in_(list(who))).order_by(m.id)).all()
    up = [mid for mid, presence in presences_of(conn, rows).items() if presence == "online"]
    # A person who keeps their online status off is left out whole: a count beside the
    # names would point at them.
    people = [who[i] for i in up if i in who and who[i].presence_named]
    named = sorted(
        (p for p in people if p.shown),
        key=lambda p: (not p.human, p.handle or "", p.id),
    )
    return {
        "humans": sum(1 for p in people if p.human),
        "agents": sum(1 for p in people if not p.human),
        "named": [_shown(p) for p in named],
    }


def html(entries: list[dict[str, Any]], up: dict[str, Any]) -> str:
    """The two parts of the project's page; every text is escaped, a link only `https`."""

    def item(entry: dict[str, Any]) -> str:
        text = escape(entry["text"])
        if entry["url"]:
            text = f'<a href="{escape(entry["url"], quote=True)}" rel="nofollow ugc">{text}</a>'
        when = escape(entry["at"], quote=True)
        return f'<li><time datetime="{when}">{escape(entry["at"][:10])}</time> {text}</li>'

    recent = (
        f'<h2>Recently</h2><ul class="ticker">{"".join(item(e) for e in entries)}</ul>'
        if entries
        else ""
    )
    names = "".join(
        f"<li>{escape(p['name'])} ({escape(p['handle'])})</li>" for p in up["named"] if p
    )
    count = f"<p>{up['humans']} human(s) and {up['agents']} agent(s) online</p>"
    return f"{recent}<h2>Online</h2>{count}" + (f"<ul>{names}</ul>" if names else "")


class Worker:
    """Renders every public project page again every `public_pages_snapshot_minutes`, one
    replica at a time, so the snapshot follows without a connection per visitor."""

    def __init__(self, engine: Engine, hub: Settings, interval: float | None = None) -> None:
        self.engine = engine
        self.hub = hub
        self.interval = hub.public_pages_snapshot_minutes * 60.0 if interval is None else interval
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if not self.hub.public_pages:
            return
        self._thread = threading.Thread(target=self._run, name="maity-public-snapshot", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)

    def run_once(self) -> None:
        from maity_hub import public_projects

        with self.engine.connect() as conn:
            ids = public_projects.targets(conn)
        for project_id in ids:
            with self.engine.begin() as conn:
                public_pages.refresh(conn, self.hub, public_projects.KIND, project_id)

    def _run(self) -> None:
        while not self._stop.wait(self.interval):
            try:
                with worker_runs.claim(
                    self.engine, "public-snapshot", self.interval, self._stop
                ) as held:
                    if held is not None:
                        self.run_once()
            except Exception:
                log.exception("rendering the public snapshots failed")
