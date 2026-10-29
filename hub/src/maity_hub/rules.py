"""The generated rules text and its version (docs/api.md §6.9).

The rules a member reads are generated from the live policy, the project
state, the member's role and the owner's text, never kept in the
repository. Every change of an input bumps `rules_version` and is marked
by an event, whose `seq` the project keeps as `rules_changed_seq`.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Connection, update

from maity_hub import namespace
from maity_hub import tables as t
from maity_hub.events import Actor, emit, lock_project

KEEP_THE_WHY = "Load the keep-the-why skill and read context/index.md before working."

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


def generate(project: Any, trust: str, role: str, arbiter: str, *, supervised: bool = False) -> str:
    """The rules document for one member of `project`; `supervised` for a session a
    runner supervises (§15.11)."""
    lines = [f"# Rules for {project.name}", "", f"Rules version {project.rules_version}.", ""]
    lines += ["## State", "", _STATE.get(project.state, f"State: {project.state}.")]
    if project.state_note:
        lines += ["", f"Note: {project.state_note}"]
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
        _ROLE.get(role, f"Your role is {role}."),
        "",
        "## Group chats",
        "",
        GROUP_CHATS,
    ]
    if supervised:
        lines += ["", "## Supervised", "", SUPERVISED]
    if project.keep_the_why:
        lines += ["", "## Keep the Why", "", KEEP_THE_WHY]
    if project.rules_markdown:
        lines += ["", "## From the owner", "", project.rules_markdown]
    return "\n".join(lines) + "\n"


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
