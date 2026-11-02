"""Seed the accounts of the load test (hub/context/replicas.md cac80c88) into a test system's
database, and write what `run.js` needs. Run from `hub/`:

    LOADTEST_CONFIRMED_TEST_SYSTEM=<database host> \
    MAITY_DATABASE_URL=... python loadtest/seed.py --humans 20000 --out /secure/accounts.json

The output holds session cookies and signing keys of the test system: keep it out of the repository.

Directly in the database, not through the API as the plan first said: the API's limits on logins
and on agents per human are what the run measures, and seeding would have to lift them.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import Engine, create_engine, select

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from maity_hub import tables as t  # noqa: E402
from maity_hub.auth import sessions  # noqa: E402
from tests import factory  # noqa: E402

AGENTS_PER_HUMAN = 2
SLUG = "load"


def refusal(database_url: str, confirmed: str | None) -> str | None:
    """Why this database is not seeded. A socket has no host in the URL's netloc, so a URL
    without a host confirms by its text, which nobody types by accident."""
    parts = urlsplit(database_url)
    if parts.scheme.startswith("sqlite"):
        return None
    host = parts.hostname or database_url
    if confirmed != host:
        return f"LOADTEST_CONFIRMED_TEST_SYSTEM does not name {host}"
    return None


def seed_one(engine: Engine, n: int) -> dict[str, Any]:
    handle = f"load-{n}"
    human_id = factory.human(engine, handle)
    project_id = factory.project(engine, SLUG, owner_id=human_id)
    factory.membership(engine, project_id, "owner", human_id=human_id)
    agents = [
        factory.agent(engine, project_id, human_id, instance=f"lo{k}a")
        for k in range(AGENTS_PER_HUMAN)
    ]
    with engine.begin() as conn:
        cookie, _, _ = sessions.create(
            conn, human_id, method="password", address="192.0.2.1", user_agent="k6"
        )
    return {
        "handle": handle,
        "owner": handle,
        "slug": SLUG,
        "session": cookie,
        "agents": [
            {"agent_id": a.agent_id, "credential_id": a.credential_id, "verifier": a.verifier}
            for a in agents
        ],
    }


def first_free(engine: Engine) -> int:
    with engine.connect() as conn:
        taken = conn.execute(select(t.human.c.handle).where(t.human.c.handle.like("load-%")))
        return 1 + max((int(h.removeprefix("load-")) for (h,) in taken), default=-1)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--humans", type=int, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    url = os.environ["MAITY_DATABASE_URL"]
    why = refusal(url, os.environ.get("LOADTEST_CONFIRMED_TEST_SYSTEM"))
    if why is not None:
        print(f"refused: {why}", file=sys.stderr)
        return 2
    engine = create_engine(url)
    start = first_free(engine)
    humans = [seed_one(engine, start + n) for n in range(args.humans)]
    args.out.touch(mode=0o600)
    args.out.write_text(json.dumps(humans))
    print(f"seeded {len(humans)} humans into {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
