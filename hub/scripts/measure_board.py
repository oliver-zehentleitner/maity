"""Measure what the dashboard asks for when it opens a project: the board, the
members and an events page, with the number of SQL statements each request runs.

    python scripts/measure_board.py [--database-url URL] [--cards 200] [--members 10]
                                    [--events 2000] [--rounds 20] [--rtt-ms 0]

Run from hub/ with the dev dependencies installed. Without --database-url the
hub uses SQLite in a temporary directory. A server database must be one the
script may wipe: the schema is dropped and migrated first. --rtt-ms puts a TCP
proxy between the hub and a server database that delays every chunk by half
the given round trip in each direction, as a database across a cluster network
would be; the statement count times the round trip is then what each request
pays on top.

The hub runs in-process behind the ASGI test client, so the times are the
hub's own work and the database's, without HTTP over a socket.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import random
import statistics
import sys
import tempfile
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # tests.factory

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import Engine, event, insert  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402

from maity_hub import clock  # noqa: E402
from maity_hub import tables as t  # noqa: E402
from maity_hub.app import create_app  # noqa: E402
from maity_hub.config import Settings, normalize_database_url  # noqa: E402
from maity_hub.db import downgrade, make_engine, migrate  # noqa: E402
from tests import factory  # noqa: E402

STATUSES = ("open", "claimed", "in_progress", "review", "done", "blocked")


def seed(engine: Engine, cards: int, members: int, events: int) -> str:
    """A project with an owner, members - 1 agents, cards with claims and edges, events,
    and releases: one open, and one closed per ten cards (frozen, every second tagged)."""
    rng = random.Random(7)
    owner_id = factory.human(engine, "owner")
    project_id = factory.project(engine, "measure")
    owner = factory.membership(engine, project_id, "owner", human_id=owner_id)
    agents = [factory.agent(engine, project_id, owner_id) for _ in range(members - 1)]
    memberships = [owner] + [a.membership_id for a in agents]
    now = clock.now()
    card_ids: list[str] = []
    for n in range(cards):
        status = STATUSES[n % len(STATUSES)]
        holder = rng.choice(agents) if status in ("claimed", "in_progress") else None
        card_ids.append(
            factory.card(
                engine,
                project_id,
                rng.choice(memberships),
                title=f"Card {n}",
                status=status,
                assigned_to=rng.choice(memberships) if n % 2 else None,
                claim_holder=holder.membership_id if holder else None,
                claim_session_id=holder.session_id if holder else None,
                claim_since=now if holder else None,
                lease_until=now + timedelta(hours=2) if holder else None,
                updated_at=now - timedelta(seconds=n),
            )
        )
    with engine.begin() as conn:
        for n, card_id in enumerate(card_ids[1:], start=1):
            if n % 2:
                conn.execute(
                    insert(t.card_edge).values(
                        from_card=card_id, to_card=card_ids[n - 1], kind="depends_on"
                    )
                )
            if n % 10 == 0:
                conn.execute(
                    insert(t.card_edge).values(
                        from_card=card_id, to_card=card_ids[n - 2], kind="ships_with"
                    )
                )
        conn.execute(
            insert(t.event),
            [
                {
                    "project_id": project_id,
                    "kind": "task_updated",
                    "at": now,
                    "actor_membership": rng.choice(memberships),
                    "subject_type": "task",
                    "subject_id": rng.choice(card_ids),
                    "audience": ["all"],
                    "payload": {"task": rng.choice(card_ids), "changed": ["status"]},
                    "redacted": False,
                }
                for _ in range(events)
            ],
        )
    _releases(engine, project_id, owner, cards // 10)
    return project_id


def _releases(engine: Engine, project_id: str, owner: int, closed: int) -> None:
    now = clock.now()
    factory.card(
        engine,
        project_id,
        owner,
        title="Release 1.0.0",
        kind="release",
        status="open",
        release_version="1.0.0",
        release_in_flight=True,
        release_data={"version": "1.0.0", "checklist": [], "pull_requests_typed": []},
    )
    frozen = {"pull_requests": [], "groups": [], "readiness": {"ready": True, "blocking": []}}
    for n in range(closed):
        version = f"0.{n + 1}.0"
        factory.card(
            engine,
            project_id,
            owner,
            title=f"Release {version}",
            kind="release",
            status="done",
            closed_at=now,
            release_version=version,
            release_data={"version": version, "checklist": [], "frozen": frozen},
            updated_at=now - timedelta(days=1, seconds=n),
        )
        if n % 2 == 0:
            with engine.begin() as conn:
                conn.execute(
                    insert(t.forge_observation).values(
                        project_id=project_id,
                        kind="tag",
                        ref=f"v{version}",
                        observed_at=now,
                        data={"name": f"v{version}", "sha": "a" * 40, "found": True},
                    )
                )


@contextlib.contextmanager
def counting(engine: Engine) -> Iterator[Callable[[], int]]:
    """The number of statements executed while the block runs."""
    seen = [0]

    def count(*_args: Any) -> None:
        seen[0] += 1

    event.listen(engine, "before_cursor_execute", count)
    try:
        yield lambda: seen[0]
    finally:
        event.remove(engine, "before_cursor_execute", count)


@contextlib.contextmanager
def delay_proxy(host: str, port: int, rtt_ms: float) -> Iterator[int]:
    """A TCP proxy on loopback to host:port that holds each chunk for rtt/2."""
    loop = asyncio.new_event_loop()
    half = rtt_ms / 2000
    ready = threading.Event()
    bound: list[int] = []

    async def pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            while data := await reader.read(65536):
                await asyncio.sleep(half)
                writer.write(data)
                await writer.drain()
        except (ConnectionError, asyncio.CancelledError):
            pass
        finally:
            writer.close()

    async def handle(client_r: asyncio.StreamReader, client_w: asyncio.StreamWriter) -> None:
        server_r, server_w = await asyncio.open_connection(host, port)
        await asyncio.gather(pipe(client_r, server_w), pipe(server_r, client_w))

    async def main() -> None:
        server = await asyncio.start_server(handle, "127.0.0.1", 0)
        bound.append(server.sockets[0].getsockname()[1])
        ready.set()
        async with server:
            await server.serve_forever()

    thread = threading.Thread(target=lambda: loop.run_until_complete(main()), daemon=True)
    thread.start()
    ready.wait(5)
    try:
        yield bound[0]
    finally:
        loop.call_soon_threadsafe(loop.stop)


def measure(client: TestClient, engine: Engine, path: str, rounds: int) -> dict[str, Any]:
    times, counts, size = [], [], 0
    for _ in range(rounds):
        with counting(engine) as seen:
            started = time.perf_counter()
            response = client.get(f"/api/v1{path}")
            times.append((time.perf_counter() - started) * 1000)
        assert response.status_code == 200, response.text
        counts.append(seen())
        size = len(response.json().get("items", []))
    times.sort()
    return {
        "path": path,
        "items": size,
        "statements": statistics.median(counts),
        "median_ms": statistics.median(times),
        "p95_ms": times[max(0, int(len(times) * 0.95) - 1)],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--database-url")
    parser.add_argument("--cards", type=int, default=200)
    parser.add_argument("--members", type=int, default=10)
    parser.add_argument("--events", type=int, default=2000)
    parser.add_argument("--rounds", type=int, default=20)
    parser.add_argument("--rtt-ms", type=float, default=0.0)
    args = parser.parse_args()

    with contextlib.ExitStack() as stack:
        url = args.database_url
        if url is None:
            url = f"sqlite:///{stack.enter_context(tempfile.TemporaryDirectory())}/hub.db"
        url = normalize_database_url(url)
        setup = make_engine(url)
        downgrade(setup)
        migrate(setup)
        project_id = seed(setup, args.cards, args.members, args.events)
        setup.dispose()
        if args.rtt_ms and not url.startswith("sqlite"):
            parsed = make_url(url)
            port = stack.enter_context(
                delay_proxy(parsed.host or "127.0.0.1", parsed.port or 5432, args.rtt_ms)
            )
            url = parsed.set(host="127.0.0.1", port=port).render_as_string(hide_password=False)
        engine = make_engine(url)
        settings = replace(Settings.from_env({"MAITY_DATABASE_URL": url}), web_dir=None)
        client = stack.enter_context(
            TestClient(create_app(settings, engine), base_url="https://hub.example")
        )
        login = client.post(
            "/api/v1/auth/login", json={"handle": "owner", "password": factory.PASSWORD}
        )
        assert login.status_code == 200, login.text
        slug = "measure"
        paths = [
            f"/projects/{slug}/tasks?status=all&limit=200",
            f"/projects/{slug}/tasks?status=all&limit=50",
            f"/projects/{slug}/members",
            f"/projects/{slug}/events?after=0&limit=200",
        ]
        dialect = make_url(url).get_backend_name()
        print(
            f"{dialect}, {args.cards} cards, {args.members} members, {args.events} events, "
            f"rtt {args.rtt_ms:g} ms, {args.rounds} rounds (project {project_id})"
        )
        print(f"{'request':<48} {'items':>5} {'stmts':>6} {'median ms':>10} {'p95 ms':>8}")
        for path in paths:
            row = measure(client, engine, path, args.rounds)
            print(
                f"{row['path']:<48} {row['items']:>5} {row['statements']:>6g} "
                f"{row['median_ms']:>10.1f} {row['p95_ms']:>8.1f}"
            )
        engine.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(main())
