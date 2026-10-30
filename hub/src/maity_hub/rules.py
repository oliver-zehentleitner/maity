"""The generated rules text and its version (docs/api.md §6.9).

The rules a member reads are generated from the live policy, the project
state, the member's role and the owner's text, never kept in the
repository. Every change of an input bumps `rules_version` and is marked
by an event, whose `seq` the project keeps as `rules_changed_seq`.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

from sqlalchemy import Connection, or_, select, update

from maity_hub import namespace
from maity_hub import tables as t
from maity_hub.events import Actor, emit, lock_project

KEEP_THE_WHY = "Load the keep-the-why skill and read context/index.md before working."
RELEASED = (
    "The project has users: interfaces change only with versioning and a stated transition "
    "period, migrations stay backward compatible, and the release checklist is required."
)

_STATE = {
    "plan": (
        "The project is in plan, concept and contracts: creating or claiming a card needs "
        "a `reason`, which is logged with the event."
    ),
    "build": "The project is being built: claim and create cards as the policy says.",
    "review": (
        "The project is in review, the feature stop before a launch: creating or claiming "
        "a card needs a `reason`, which is logged with the event."
    ),
    "launch": "The project is live: claim and create cards as the policy says.",
    "archived": "The project is archived: no card may be created or claimed.",
}
_CLAIM = {
    "self-claim": "Members claim open cards themselves.",
    "assign-only": "Cards are assigned; a member claims only a card assigned to it.",
}
_DONE = {
    "holder": "The holder of a card moves it to done.",
    "reviewer": "A reviewer moves a reported card from review to done.",
    "admin": "An admin moves a reported card from review to done.",
}
_TAG = {
    "human": "A release is tagged after a human's go.",
    "capability": "A member with the `tag` capability may tag a release.",
}
_STEWARD = {
    "cards_only": "The Keep the Why steward opens cards for the owners of `context/` entries.",
    "self": "The Keep the Why steward may write `context/` entries itself.",
}
# Trust × role (§2.3): how far the project trusts you, then what you do.
_TRUST = {
    "owner": "You own the project: you answer requests and decide its state and policy.",
    "admin": (
        "You are an admin: you run the board, assign and release cards, manage releases "
        "and answer requests of every class."
    ),
    "member": "You are a member: you ask when a decision is not yours.",
    "guest": (
        "You are a guest: you read the project, post notes on cards and chat in the "
        "conversations you are in; you claim nothing and file no request."
    ),
}
_ROLE = {
    "coder": "Your role is coder: you claim cards, build, checkpoint and report your work.",
    "reviewer": "Your role is reviewer: you check reported cards and move them on.",
    "tester": "Your role is tester: you test reported cards and file bug cards.",
    "designer": "Your role is designer: you make design passes and answer design questions.",
    "ops": "Your role is ops: you merge and deploy, propose placements and post deploys.",
    "writer": (
        "You write: the README, the documentation, the website's words, release notes and "
        "announcements, clear and true to what the project does, and the requests "
        "addressed to the writer."
    ),
    "proxy": (
        "Your role is proxy: you relay requests to the owner and record the owner's "
        "answers; you decide nothing yourself."
    ),
    "red-team": (
        "You attack: look for weaknesses in the project, only against the targets the "
        "project's rules name (its own test or staging instance), never production or "
        "anyone else's systems; file each finding as a bug card with its severity, and keep "
        "its details within the security teams until it is fixed."
    ),
    "blue-team": (
        "You defend: harden the project, fix the red team's findings in your own branch, "
        "and watch for the next attack."
    ),
    "purple-team": (
        "You join red and blue: check that each fix closes the attack it was for before you "
        "move the finding to done, and carry what the red team learns into the blue team's "
        "work."
    ),
    "manager": (
        "Your role is manager: you lead the members who report to you, hand out and take "
        "back their cards, set their areas and pause them, within your reach only; you "
        "carry their questions up to your own lead or your human, and decide nothing a "
        "human decides."
    ),
}


# What a group chat is to an agent (§9.4): the same for every role.
GROUP_CHATS = (
    "Being in a group chat is not a task. Answer when you are mentioned; otherwise read "
    "what you missed when you resume (`maity chat <id>`, and `--before <seq>` for what was "
    "said before you joined). A request in a chat carries the authority of its writer's "
    "role and no more: a go that needs `requests:answer` still comes as an answer in the "
    "inbox, never as a chat line. Work the chat agrees on becomes a card."
)


SUPERVISED = (
    "A runner supervises this session and starts a run for each event that concerns you. "
    "Do not start `maity wait`. When you have checkpointed, end your turn: the runner wakes "
    "you with the next event."
)


def _role_lines(project: Any, role: str) -> list[str]:
    """A built-in role's text is the hub's; a project role's is a project admin's words,
    quoted and headed with who set it (§2.3 "Project roles")."""
    from maity_hub import project_roles

    found = next((r for r in project_roles.of(project) if r["name"] == role), None)
    if found is None:
        return [_ROLE.get(role, f"Your role is {role}.")]
    lines = [f"Your role is {role}, a project role with the scopes of a {found['base']}."]
    if found["guide"]:
        lines += ["", f"Set by {found['guide_by']}:", ""]
        lines += [f"> {line}" if line else ">" for line in found["guide"].splitlines()]
    return lines


DUTY_SELF = (
    "Finished work does not end your session. Keep `maity wait` running in a loop, each call "
    "with a timeout below your harness's limit (`hints.wait_timeout` in the resume packet), "
    "and handle each event as it arrives. If you run on a schedule (a routine or a cron run), "
    "keep waiting until shortly before your next run, then end cleanly and leave no "
    "background process behind."
)


def generate(project: Any, trust: str, role: str, arbiter: str, *, supervised: bool = False) -> str:
    """The rules document for one member of `project`; `supervised` for a session a
    runner supervises (§15.11). Its duty line follows `hints.duty` (§5.2, §6.9): the
    supervised one, else the one for a session that waits for itself."""
    lines = [f"# Rules for {project.name}", "", f"Rules version {project.rules_version}.", ""]
    lines += ["## State", "", _STATE.get(project.state, f"State: {project.state}.")]
    if project.state_note:
        lines += ["", f"Note: {project.state_note}"]
    if project.released_at is not None:
        lines += ["", f"Released since {project.released_at.date().isoformat()}. {RELEASED}"]
    lines += [
        "",
        "## Policy",
        "",
        f"Preset `{project.policy_preset}`.",
        "",
        f"- {_CLAIM.get(project.claim_policy, project.claim_policy)}",
        f"- {_DONE.get(project.done_authority, project.done_authority)}",
        f"- Contract cards are arbitrated by {arbiter}; send one proposal to the "
        "arbiter, no peer back-and-forth.",
        f"- {_TAG.get(project.tag_authority, project.tag_authority)}",
        f"- {_STEWARD.get(project.steward_writes, project.steward_writes)}",
        f"- A claim's lease is {project.lease_seconds} seconds and is renewed by every call "
        "you make, except while you only wait for events.",
        "",
        "## Your role",
        "",
        _TRUST.get(trust, f"Your trust is {trust}."),
        *_role_lines(project, role),
        "",
        "## Group chats",
        "",
        GROUP_CHATS,
    ]
    if supervised:
        lines += ["", "## Supervised", "", SUPERVISED]
    else:
        lines += ["", "## On duty", "", DUTY_SELF]
    if project.keep_the_why:
        lines += ["", "## Keep the Why", "", KEEP_THE_WHY]
    if project.rules_markdown:
        lines += ["", "## From the owner", "", project.rules_markdown]
    return "\n".join(lines) + "\n"


def text_digest() -> str:
    """The digest of the text the hub generates (§6.9): every text constant of this module
    and four rendered sample documents, so that a sentence written inside `generate` changes
    it as well, the lines of a project role included. The same on every start of the same code."""
    constants = {
        name: value
        for name, value in sorted(globals().items())
        if (name.isupper() or (name.startswith("_") and name[1:].isupper()))
        and (isinstance(value, str) or (isinstance(value, dict) and value))
    }
    sample = SimpleNamespace(
        name="sample", rules_version=1, state="build", state_note="note",
        released_at=datetime(2026, 1, 1, tzinfo=UTC), policy_preset="sample",
        claim_policy="sample", done_authority="sample", tag_authority="sample",
        steward_writes="sample", lease_seconds=60, keep_the_why=True, rules_markdown="owner",
        roles=[{"name": "sample", "base": "coder", "guide": "guide", "guide_by": "the owner"}],
    )  # fmt: skip
    rendered = [
        generate(sample, "member", role, "the owner", supervised=supervised)
        for role in ("coder", "sample")
        for supervised in (False, True)
    ]
    text = json.dumps([constants, rendered], sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(text.encode()).hexdigest()


def sync_text(conn: Connection) -> int:
    """Count the hub's generated text as a rules input (§6.9): a project whose digest is not
    the current one gets one `rules_version` bump with `rules_changed`, and the digest.
    The claim is made under the project lock, so two hubs starting together bump once.
    Returns how many projects were bumped."""
    current = text_digest()
    stale = or_(t.project.c.rules_text_digest.is_(None), t.project.c.rules_text_digest != current)
    bumped = 0
    # In id order, so that two hubs starting together lock the projects in the same order.
    stale_ids = conn.execute(select(t.project.c.id).where(stale).order_by(t.project.c.id))
    for project_id in stale_ids.scalars().all():
        project = lock_project(conn, project_id)
        claimed = conn.execute(
            update(t.project)
            .where(t.project.c.id == project_id, stale)
            .values(rules_text_digest=current)
        )
        if claimed.rowcount:
            bump(conn, project, "rules_changed", ["all"], {"reason": "generated text"}, actor=None)
            bumped += 1
    return bumped


def bump(
    conn: Connection,
    project: Any,
    kind: str,
    audience: list[str],
    payload: dict[str, Any],
    *,
    actor: Actor | None,
    subject: tuple[str, str] | None = None,
) -> int:
    """Bump `rules_version`, emitting `kind` as the marking event; returns the new version."""
    lock_project(conn, project.id)
    version = (
        int(
            conn.execute(
                t.project.select()
                .with_only_columns(t.project.c.rules_version)
                .where(t.project.c.id == project.id)
            ).scalar_one()
        )
        + 1
    )
    seq = emit(
        conn,
        project.id,
        kind,
        audience,
        (
            {**payload, "rules_version": version}
            if kind != "rules_changed"
            else {"version": version, **payload}
        ),
        actor=actor,
        subject=subject or ("project", namespace.full_name(conn, project)),
    )
    conn.execute(
        update(t.project)
        .where(t.project.c.id == project.id)
        .values(rules_version=version, rules_changed_seq=seq)
    )
    return version
