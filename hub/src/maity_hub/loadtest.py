"""The load test's accounts (hub/context/replicas.md cac80c88): `maity-hub loadtest seed`, run where
the hub runs, against the hub's own database.

Every account is named `lt-<n>`, so that what the run made is found by its prefix and nothing else
is. Each is a human with its own project `lt-<n>/load` and two agents in it, signed in: the output
holds a session cookie per human and a signing key per agent, which is what `loadtest/run.js` reads.
A human has no mail address, so nothing the run does can send a mail.

Directly in the database, not through the API: the API's limits on logins and on agents per human
are what the run measures, and seeding through it would have to lift them. The rows are the ones
the routes write, through the same helpers where there are any.

A hub is seeded only when the operator names it: `LOADTEST_CONFIRMED_TEST_SYSTEM` names the host of
`MAITY_PUBLIC_URL`; for a host under `maity.team`, which may be production, only
`LOADTEST_CONFIRMED_PRODUCTION` does.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import Engine, insert, select

from maity_hub import clock, handle_register, handles, namespace, policy, rules, setup_cards
from maity_hub import tables as t
from maity_hub.auth import credentials, sessions
from maity_hub.ids import new_id

PREFIX = "lt-"
SLUG = "load"
AGENTS_PER_HUMAN = 2
PRODUCTION = "maity.team"
# Not a scrypt hash: `passwords.verify_password` answers False for it, so no one signs in with it.
NO_PASSWORD = "loadtest"


def refusal(public_url: str, test_system: str | None, production: str | None) -> str | None:
    """Why this hub is not seeded, or None. The host is the one of the hub's own public URL, so
    the name the operator gives is checked against where the command runs."""
    host = (urlsplit(public_url).hostname or "").lower()
    if not host:
        return "MAITY_PUBLIC_URL names no host"
    if host == PRODUCTION or host.endswith(f".{PRODUCTION}"):
        if production != host:
            return f"{host} may be production: LOADTEST_CONFIRMED_PRODUCTION does not name it"
        return None
    if test_system != host:
        return f"LOADTEST_CONFIRMED_TEST_SYSTEM does not name {host}"
    return None


def first_free(engine: Engine) -> int:
    """The next number after every `lt-<n>` handle, so a second seed adds accounts."""
    with engine.connect() as conn:
        taken = conn.execute(select(t.human.c.handle).where(t.human.c.handle.like(f"{PREFIX}%")))
        numbers = (h.removeprefix(PREFIX) for (h,) in taken)
        return 1 + max((int(n) for n in numbers if n.isdigit()), default=-1)


def seed_one(engine: Engine, n: int) -> dict[str, Any]:
    """One human `lt-<n>` with its project and agents, in one transaction; what `run.js` needs."""
    handle = f"{PREFIX}{n}"
    now = clock.now()
    with engine.begin() as conn:
        human_id = new_id("human")
        handles.lock(conn, handles.HUMANS, handle)
        conn.execute(
            insert(t.human).values(
                id=human_id,
                handle=handle,
                display_name=f"Load test {n}",
                password_hash=NO_PASSWORD,
                created_at=now,
            )
        )
        if not handle_register.claim(conn, handle, handle_register.HUMAN, human_id):
            raise RuntimeError(f"the handle {handle} is taken")
        project_id = new_id("project")
        conn.execute(
            insert(t.project).values(
                id=project_id,
                **namespace.owner_values(human_id),
                slug=SLUG,
                name="Load test",
                state="build",
                state_changed_at=now,
                keep_the_why=False,
                setup=setup_cards.stored(setup_cards.parse(None, False)),
                public_page="off",
                **policy.columns(policy.filled("hierarchical", human_id)),
                settings={"release_checklist": []},
                rules_version=1,
                rules_text_digest=rules.text_digest(),
                created_at=now,
            )
        )
        conn.execute(
            insert(t.membership).values(
                project_id=project_id,
                human_id=human_id,
                trust="owner",
                role="coder",
                role_base="coder",
                areas=["/"],
                capabilities=[],
                joined_at=now,
            )
        )
        agents = []
        for k in range(AGENTS_PER_HUMAN):
            agent_id = new_id("agent")
            conn.execute(
                insert(t.agent_profile).values(
                    id=agent_id,
                    owner_id=human_id,
                    handle=f"agent-{k}",
                    display_name=f"Load test {n} agent {k}",
                    created_at=now,
                )
            )
            result = conn.execute(
                insert(t.membership).values(
                    project_id=project_id,
                    agent_id=agent_id,
                    trust="member",
                    role="coder",
                    role_base="coder",
                    areas=["/"],
                    capabilities=[],
                    joined_at=now,
                )
            )
            key = result.inserted_primary_key
            assert key is not None
            membership_id = int(key[0])
            credential_id = new_id("credential")
            _, verifier = credentials.issue(credential_id)
            conn.execute(
                insert(t.credential).values(
                    id=credential_id,
                    membership_id=membership_id,
                    instance=f"lt{k}a",
                    verifier=verifier,
                    created_at=now,
                )
            )
            conn.execute(
                insert(t.agent_session).values(
                    id=new_id("session"),
                    credential_id=credential_id,
                    membership_id=membership_id,
                    harness="k6",
                    started_at=now,
                    last_seen_at=now,
                    acknowledged_seq=0,
                    live=True,
                )
            )
            agents.append(
                {"agent_id": agent_id, "credential_id": credential_id, "verifier": verifier}
            )
        cookie, _, _ = sessions.create(
            conn, human_id, method="password", address="192.0.2.1", user_agent="k6"
        )
    return {"handle": handle, "owner": handle, "slug": SLUG, "session": cookie, "agents": agents}


def seed(engine: Engine, humans: int, out: Path) -> int:
    """Seed `humans` accounts and write them to `out`, a new file only its owner reads. What an
    interrupted seed made is written too: still usable, and still found by the prefix."""
    start = first_free(engine)
    descriptor = os.open(out, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    made: list[dict[str, Any]] = []
    try:
        for n in range(humans):
            made.append(seed_one(engine, start + n))
    finally:
        with os.fdopen(descriptor, "w") as file:
            json.dump(made, file)
    return len(made)
