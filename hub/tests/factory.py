"""Rows for tests: humans, projects, memberships, agents with credentials."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from sqlalchemy import Engine, insert, inspect, select

from maity_hub import clock
from maity_hub import tables as t
from maity_hub.auth import credentials
from maity_hub.auth.passwords import hash_password
from maity_hub.ids import new_id

PASSWORD = "correct horse battery staple"
_HASH = hash_password(PASSWORD)  # scrypt is slow on purpose; hash once per run


def human(engine: Engine, handle: str | None = None) -> str:
    """A human row. `maintainer` is the one `project` may have made already as the namespace
    owner (§6.25): asked for again, it is that human."""
    human_id = new_id("human")
    with engine.begin() as conn:
        if handle == "maintainer":
            found = conn.execute(select(t.human.c.id).where(t.human.c.handle == handle)).scalar()
            if isinstance(found, str):
                return found
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


def _namespaced(engine: Engine) -> bool:
    """Whether the database is at a revision with the project namespace (§6.25)."""
    return any(c["name"] == "owner_id" for c in inspect(engine).get_columns("project"))


def _maintainer(engine: Engine) -> str:
    with engine.begin() as conn:
        found = conn.execute(select(t.human.c.id).where(t.human.c.handle == "maintainer")).scalar()
    return found if isinstance(found, str) else human(engine, "maintainer")


def project(engine: Engine, slug: str | None = None, **values: Any) -> str:
    """A project row. Its namespace owner (§6.25) is `owner_id` when given, else the human
    `maintainer`, made here when missing: the owner `tests/flow.py` creates projects with,
    so that a test's paths are `/projects/maintainer/<slug>` either way."""
    project_id = new_id("project")
    if "owner_id" not in values and _namespaced(engine):
        values = {**values, "owner_id": _maintainer(engine)}
    row: dict[str, Any] = {
        "id": project_id,
        "slug": slug or project_id,
        "name": f"Project {slug or project_id}",
        "state": "build",
        "state_changed_at": clock.now(),
        "keep_the_why": False,
        "policy_preset": "hierarchical",
        "claim_policy": "self-claim",
        "done_authority": "reviewer",
        "contract_arbiter": "trust:admin",
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


# The single role's names, as most tests still say them, to trust × role (§2.3); a role
# of the new model passes through with trust `member`, unless `trust` is given.
SINGLE_ROLE = {
    "owner": ("owner", "coder"),
    "admin": ("admin", "coder"),
    "proxy": ("admin", "proxy"),
    "reviewer": ("member", "reviewer"),
    "member": ("member", "coder"),
    "guest": ("guest", "coder"),
}


def trust_and_role(role: str, trust: str | None = None) -> tuple[str, str]:
    if trust is not None:
        return trust, role
    return SINGLE_ROLE.get(role, ("member", role))


def membership(
    engine: Engine, project_id: str, role: str = "owner", trust: str | None = None, **principal: str
) -> int:
    values: dict[str, Any] = {"role": role}  # before 0067, the single role (§2.3)
    if "trust" in {c["name"] for c in inspect(engine).get_columns("membership")}:
        values["trust"], values["role"] = trust_and_role(role, trust)
    with engine.begin() as conn:
        result = conn.execute(
            insert(t.membership).values(
                project_id=project_id,
                areas=["/"],
                capabilities=[],
                joined_at=clock.now(),
                **values,
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
    trust: str | None = None,
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
    membership_id = membership(engine, project_id, role, trust, agent_id=agent_id)
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
