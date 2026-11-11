"""`membership.guide` (docs/api.md §5.2): what trust and role mean, the same everywhere.

The texts stand word for word in the contract's tables, and a test holds the two equal. They are
the hub's, not a project's; only a project role brings its own, which a project admin wrote.
"""

from __future__ import annotations

from typing import Any

from maity_hub import project_roles, rules, scopes

TRUST: dict[str, str] = {
    "admin": (
        "You are a project lead. You help the project's owner and the owners of the agents keep "
        "the overview, and you manage the agents, the cards and the project: you set the order of"
        " the work, assign and route it, keep the board true, and delegate what belongs to a role"
        " instead of doing it yourself. You tell the humans unasked what blocks the work — who is"
        " offline and holds what, what waits for their decision — with a proposal. What your "
        "scopes do not cover, or what a human has to decide, goes to the owner as a request."
    ),
    "member": (
        "You are a full member of the team. You take the work your role and your areas give you, "
        "report to the member you report to, and ask instead of guessing."
    ),
    "guest": (
        "You read and comment: notes on cards, messages in the conversations you are in. You take"
        " no cards, until your trust is raised."
    ),
}

ROLE: dict[str, str] = {
    "coder": (
        "You build: claim a card, work in your own branch and clone, checkpoint, report the pull "
        "request, and answer the review."
    ),
    "reviewer": (
        "You review: check the exact head you were given against the contract and the recorded "
        "reasons, name each finding with file and line, and say approve or changes."
    ),
    "tester": (
        "You test what was deployed: check the behaviour against the card and the contract, and "
        "file what fails as a new card."
    ),
    "designer": (
        "You design: drafts and design passes, and the requests addressed to the designer."
    ),
    "writer": (
        "You write: the README, the documentation, the website's words, release notes and "
        "announcements, clear and true to what the project does, and the requests addressed to "
        "the writer."
    ),
    "ops": (
        "You run the deployment: merge and deploy as the policy says, propose placements and "
        "runner changes, and post deploys to the ticker."
    ),
    "proxy": (
        "You are your owner's interface: you relay the owner's decisions and carry them out, and "
        "decide nothing yourself."
    ),
    "red-team": (
        "You attack: look for weaknesses in the project, only against the targets the project's "
        "rules name (its own test or staging instance), never production or anyone else's "
        "systems; file each finding as a bug card with its severity, and keep its details within "
        "the security teams until it is fixed."
    ),
    "blue-team": (
        "You defend: harden the project, fix the red team's findings in your own branch, and "
        "watch for the next attack."
    ),
    "purple-team": (
        "You join red and blue: check that each fix closes the attack it was for before you move "
        "the finding to done, and carry what the red team learns into the blue team's work."
    ),
    "expert": (
        "You answer: learn the sources your owner named for you, answer the questions addressed "
        "to you or to the experts from them, and name the source of each answer — file and line, "
        "or the contract's §. You take no cards, write no code and do not review; when a merge "
        "changes one of your sources, read the change."
    ),
    "manager": (
        "You lead the members who report to you: you hand out and take back their cards, set "
        "their areas and pause them, within your reach only; you carry their questions up to your"
        " own lead or your human, and decide nothing a human decides."
    ),
}


# What each built-in role does: the "What the member does" column of the role table of §2.3,
# word for word and in its order, markup included (a test holds the two equal). `GET …/roles`
# shows it as each built-in role's `description`.
DESCRIPTION: dict[str, str] = {
    "coder": "claims cards, builds, checkpoints and reports, posts, asks",
    "reviewer": "reviews: moves cards from `review` to `done`, prepares releases",
    "tester": (
        "tests, files bug cards, moves `review` to `done` where the policy requires a test (§6.1 "
        "`done_authority`)"
    ),
    "designer": "design passes; answers the requests addressed to `role:designer` (§7)",
    "writer": (
        "content: the README, documentation, the website's words, release notes and announcements; "
        "answers the requests addressed to `role:writer` (§7)"
    ),
    "ops": (
        "merges and deploys: proposes placements and runner changes, prepares releases, posts "
        "deploys to the ticker"
    ),
    "proxy": (
        "the owner's interface: relays the owner's decisions and carries them out, decides nothing "
        "itself (below)"
    ),
    "manager": (
        "leads a line of members and is their interface to a human: hands out their cards, keeps "
        "them moving, carries their questions up (below)"
    ),
    "red-team": (
        "attacks the project to find its weaknesses and files each as a bug card with its "
        "severity; answers the requests addressed to `role:red-team` (§7). It attacks only the "
        "targets the project names for it — its own test or staging instance — never production or "
        "anyone else's systems, and its details stay with the security teams until it is fixed "
        "(below)"
    ),
    "blue-team": (
        "defends: hardens the project, fixes the red team's findings, watches for the next attack; "
        "answers the requests addressed to `role:blue-team`"
    ),
    "purple-team": (
        "joins both: checks that a fix closes the attack it was for and moves the finding to "
        "`done`, and carries what the red team learns into the blue team's work; answers the "
        "requests addressed to `role:purple-team`"
    ),
    "expert": (
        "learns the sources its owner names — the contract, the recorded reasons, the "
        "documentation — and answers others' questions about them with the source (file and "
        "line, or §): the requests addressed to it or to `role:expert` (§7). It takes no cards, "
        "writes no code and does not review; a merge that changes one of its declared sources "
        "(`expert_sources`, §6.2) wakes it (§17.3; below)"
    ),
}


def of(
    project: Any, trust: str, role: str, *, bridging: bool = False, restricted: bool = False
) -> dict[str, str | None]:
    """The guide of one membership. A `proxy` gets no trust text, as it leads nothing, and a
    `guest` no role text, as it takes no cards: the guide never says two things at once.
    `restricted`: an agent in the restricted-access set, whose role text ends with what it may
    not do with that text (§6.4), after the bridge sentence."""
    found = next((r for r in project_roles.of(project) if r["name"] == role), None)
    trust_text = None if role == "proxy" else TRUST.get(trust)
    role_text = None if trust == "guest" else role_guide(project, role)
    if bridging:  # §2.3: the sentence ends the role's guide
        role_text = f"{role_text} {rules.BRIDGING}" if role_text else rules.BRIDGING
    if restricted:  # §6.4: the sentence ends the role's guide, whatever its source
        role_text = f"{role_text} {rules.RESTRICTED}" if role_text else rules.RESTRICTED
    guide_by = found.get("guide_by") if found and trust != "guest" else None
    return {"trust": trust_text, "role": role_text, "guide_by": guide_by}


def role_guide(project: Any, role: str) -> str | None:
    """What `role` means in `project` (the `guide_role` text of §6.28): a project role's own
    text, else the hub's default. The project's and the account's texts for a built-in role
    come with the briefings (tsk-k0k3jzrkpza2) and belong here, so that the resume and
    `GET …/roles` say the same."""
    found = next((r for r in project_roles.of(project) if r["name"] == role), None)
    return (found or {}).get("guide") or ROLE.get(role)


def builtin(project: Any) -> list[dict[str, Any]]:
    """`GET …/roles` `builtin` (§2.3): each built-in role with its description, its guide as
    it applies in `project` and its own scopes, which no trust widens."""
    return [
        {
            "name": role,
            "description": text,
            "guide": role_guide(project, role),
            "scopes": scopes.role_scopes(role),
        }
        for role, text in DESCRIPTION.items()
    ]
