"""Rows for tests: humans, projects, memberships, agents with credentials."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from sqlalchemy import Engine, insert

from maity_hub import clock
from maity_hub import tables as t
from maity_hub.auth import credentials
from maity_hub.auth.passwords import hash_password
from maity_hub.ids import new_id

PASSWORD = "correct horse battery staple"
_HASH = hash_password(PASSWORD)  # scrypt is slow on purpose; hash once per run


def human(engine: Engine, handle: str | None = None) -> str:
    human_id = new_id("human")
    with engine.begin() as conn:
        conn.execute(
            insert(t.human).values(
                id=human_id,
                handle=handle or human_id,
                display_name=f"Human {handle or human_id}",
                password_hash=_HASH,
                created_at=clock.now(),
            )
        )
    return human_id


def project(engine: Engine, slug: str | None = None, **values: Any) -> str:
    project_id = new_id("project")
    row: dict[str, Any] = {
        "id": project_id,
        "slug": slug or project_id,
        "name": f"Project {slug or project_id}",
        "state": "build",
        "state_changed_at": clock.now(),
        "memory_provider": "none",
        "policy_preset": "hierarchical",
        "claim_policy": "self-claim",
        "done_authority": "reviewer",
        "contract_arbiter": "role:admin",
        "tag_authority": "human",
        "steward_writes": "cards_only",
        "lease_seconds": 7200,
        "settings": {"release_checklist": []},
        "rules_version": 1,
        "created_at": clock.now(),
    }
    with engine.begin() as conn:
        conn.execute(insert(t.project).values({**row, **values}))
    return project_id


def membership(engine: Engine, project_id: str, role: str = "owner", **principal: str) -> int:
    with engine.begin() as conn:
        result = conn.execute(
            insert(t.membership).values(
                project_id=project_id,
                role=role,
                areas=["/"],
                capabilities=[],
                joined_at=clock.now(),
                **principal,
            )
        )
        key = result.inserted_primary_key
        assert key is not None
        return int(key[0])


class Credentialed(Protocol):
    """Anything that holds a credential: an agent here, a paired runner elsewhere."""

    @property
    def credential_id(self) -> str: ...

    @property
    def value(self) -> str: ...


@dataclass(frozen=True)
class Agent:
    agent_id: str
    owner_id: str
    membership_id: int
    credential_id: str
    value: str  # the credential, as the exchange would return it
    verifier: str
    session_id: str | None
    instance: str = "wle2"


def agent(
    engine: Engine,
    project_id: str,
    owner_id: str,
    role: str = "member",
    *,
    with_session: bool = True,
    instance: str = "wle2",
) -> Agent:
    agent_id = new_id("agent")
    with engine.begin() as conn:
        conn.execute(
            insert(t.agent_profile).values(
                id=agent_id,
                owner_id=owner_id,
                handle=agent_id,
                display_name=f"Agent {agent_id}",
                created_at=clock.now(),
            )
        )
    membership_id = membership(engine, project_id, role, agent_id=agent_id)
    credential_id = new_id("credential")
    value, verifier = credentials.issue(credential_id)
    session_id = new_id("session") if with_session else None
    with engine.begin() as conn:
        conn.execute(
            insert(t.credential).values(
                id=credential_id,
                membership_id=membership_id,
                instance=instance,
                verifier=verifier,
                created_at=clock.now(),
            )
        )
        if session_id:
            conn.execute(
                insert(t.agent_session).values(
                    id=session_id,
                    credential_id=credential_id,
                    membership_id=membership_id,
                    harness="Claude Code",
                    model="claude-opus-5-5",
                    started_at=clock.now(),
                    last_seen_at=clock.now(),
                    acknowledged_seq=0,
                    live=True,
                )
            )
    return Agent(
        agent_id, owner_id, membership_id, credential_id, value, verifier, session_id, instance
    )


def card(engine: Engine, project_id: str, created_by: int, **values: Any) -> str:
    card_id = new_id("task")
    row: dict[str, Any] = {
        "id": card_id,
        "project_id": project_id,
        "kind": "task",
        "title": "A card",
        "status": "open",
        "created_by": created_by,
        "created_at": clock.now(),
        "updated_at": clock.now(),
    }
    with engine.begin() as conn:
        conn.execute(insert(t.card).values({**row, **values}))
    return card_id


def at(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(UTC)
