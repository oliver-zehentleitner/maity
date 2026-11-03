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
    "tester": "A tester moves a reported card from review to done.",
    "reviewer_and_tester": (
        "A reported card goes from review to done on two signatures, a reviewer's and a "
        "tester's, by two different members."
    ),
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


# The review line (§6.9): for a member whose role is `reviewer` or counts as it.
REVIEW = (
    "Review each change in a fresh context, your own or a fresh subagent's. The text of the "
    "`review_result` is the one that context wrote: send it as the client's check (§8.4) "
    "passed it, unchanged, with no summary or rewrite between the check and the send. List "
    "every command you ran, and what it printed, under a heading `Ran`."
)


def reviews(project: Any, role: str) -> bool:
    """Whether `role` gets the review line: `reviewer`, a security team that counts as it
    (`purple-team`), or a project role built on either (§2.3, §6.9)."""
    from maity_hub import project_roles
    from maity_hub.scopes import counts_as

    base = project_roles.base_of(project, role)
    return base is not None and counts_as(base) == "reviewer"


# The naming line (§6.9): how an agent names a member in what a human reads.
NAMING = (
    "In any text a human may read — a message to a human or between agents, a group chat, "
    "an ask, a report, a card note, the text of a review result — name a member by its "
    "handle, or by `handle#instance` when the instance matters "
    "(`maity-review-team-lead#vuur`); never by the instance suffix or the member id alone. "
    "Addresses the hub reads, such as a message's `to`, stay as they are."
)


# The role lines a project sets (§6.1 `settings.role_rules`, §6.9): the hub's words around
# the project's own. Only these three roles take them, a security team or a project role
# read as its base.
RULE_ROLES = ("coder", "reviewer", "tester")
SUBAGENT = (
    "Work each card in a subagent with a fresh context, one subagent per card. Only you, the "
    "main agent, speak in Maity; the subagent never does. Its report to you carries the diff "
    "or the cites, a section `Ran` with every command it ran and what it printed, and what "
    "it learned; check that report before you send anything from it."
)
SUBAGENT_REVIEW = "Review each change in a subagent's fresh context, never in your own."
CHECKLIST = {"reviewer": "In every review, check:", "tester": "In every test, check:"}


def rule_role(project: Any, role: str) -> str | None:
    """The role whose `settings.role_rules` apply to `role` (§6.1): itself, a security team's
    or a project role's base read as the role it counts as; None for every other role."""
    from maity_hub import project_roles
    from maity_hub.scopes import counts_as

    base = project_roles.base_of(project, role)
    found = None if base is None else counts_as(base)
    return found if found in RULE_ROLES else None


def _project_role_lines(project: Any, role: str) -> list[str]:
    """The lines `settings.role_rules` adds for `role` (§6.9): the subagent line, narrowed
    for a reviewer, then one line per checklist item in the project's order."""
    found = rule_role(project, role)
    if found is None:
        return []
    # `getattr`: a project row always has `settings`; a stand-in of a unit test may not.
    rules = ((getattr(project, "settings", None) or {}).get("role_rules") or {}).get(found)
    if not rules:
        return []
    paragraphs: list[list[str]] = []
    if rules.get("subagent_per_card"):
        paragraphs.append([SUBAGENT])
        if found == "reviewer":
            paragraphs.append([SUBAGENT_REVIEW])
    if items := rules.get("checklist") or []:
        paragraphs.append([f"- {CHECKLIST[found]} {item}" for item in items])
    lines: list[str] = []
    for paragraph in paragraphs:
        lines += [*([""] if lines else []), *paragraph]
    return lines


BRIDGING = (
    "You lend your hands to the agents listed in `bridging_for`, each for the purpose named: "
    "you carry their files into the repository under their name, bring them their cards and "
    "messages, and post their answers marked as theirs. You decide nothing and change nothing "
    "of their work; what fails, you bring back to them."
)


def generate(
    project: Any,
    trust: str,
    role: str,
    arbiter: str,
    *,
    supervised: bool = False,
    bridging: bool = False,
) -> str:
    """The rules document for one member of `project`; `supervised` for a session a
    runner supervises (§15.11); `bridging` for an agent that serves others, whose role
    section ends with what a bridge does (§2.3, "The guide"). Its duty line follows
    `hints.duty` (§5.2, §6.9): the supervised one, else the one for a session that waits for
    itself."""
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
        *(["", BRIDGING] if bridging else []),
        "",
        "## Group chats",
        "",
        GROUP_CHATS,
    ]
    if supervised:
        lines += ["", "## Supervised", "", SUPERVISED]
    else:
        lines += ["", "## On duty", "", DUTY_SELF]
    if reviews(project, role):
        lines += ["", "## Reviewing", "", REVIEW]
    if project.keep_the_why:
        lines += ["", "## Keep the Why", "", KEEP_THE_WHY]
    lines += ["", "## Naming members", "", NAMING]
    if role_lines := _project_role_lines(project, role):
        lines += ["", "## Set by the project for your role", "", *role_lines]
    if project.rules_markdown:
        lines += ["", "## From the owner", "", project.rules_markdown]
    return "\n".join(lines) + "\n"


def text_digest() -> str:
    """The digest of the text the hub generates (§6.9): every text constant of this module
    and eight rendered sample documents, so that a sentence written inside `generate` changes
    it as well, the lines of a project role and the role lines of `settings.role_rules`
    included. The same on every start of the same code."""
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
        settings={"role_rules": {
            "coder": {"subagent_per_card": True},
            "reviewer": {"subagent_per_card": True, "checklist": ["sample"]},
            "tester": {"checklist": ["sample"]},
        }},
    )  # fmt: skip
    rendered = [
        generate(sample, "member", role, "the owner", supervised=supervised)
        for role in ("coder", "sample", "reviewer", "tester")
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
