"""Project state and policy (docs/api.md §6.1)."""

from __future__ import annotations

from typing import Any

STATES = ("build", "freeze", "fixes-only", "accepted", "archived")
CLOSED_STATES = ("accepted", "archived")
REASON_STATES = ("freeze", "fixes-only")

PRESETS = ("hierarchical", "solo", "pool", "decentral", "hybrid")
_HIERARCHICAL = {
    "claim_policy": "self-claim",
    "done_authority": "reviewer",
    "contract_arbiter": "role:admin",
    "tag_authority": "human",
    "steward_writes": "cards_only",
    "signing": "optional",
    "spawn_requests": "consent",
    "spawn_consent_by": "human",
}
_FILLINGS = {
    "hierarchical": _HIERARCHICAL,
    # solo: the owner arbitrates; filled() puts the owner's member id in.
    "solo": {**_HIERARCHICAL, "done_authority": "holder"},
    # Named shells with the hierarchical filling until an experiment defines them.
    "pool": _HIERARCHICAL,
    "decentral": _HIERARCHICAL,
    "hybrid": _HIERARCHICAL,
}
CHOICES = {
    "claim_policy": ("self-claim", "assign-only"),
    "done_authority": ("holder", "reviewer", "admin"),
    "tag_authority": ("human", "capability"),
    "steward_writes": ("cards_only", "self"),
    "signing": ("optional", "required"),
    "spawn_requests": ("off", "consent", "direct"),
    "spawn_consent_by": ("human", "role"),
    "on_runner_revoke": ("keep", "stop", "inherit"),
    "badge": ("off", "members", "agents_online"),
    "subtasks": ("proposed", "direct"),
    "swarm_public": ("off", "on"),
    "keep_the_why": ("required", "optional"),
    "keep_the_why_defaults": ("adopt", "ask"),
}
LEASE_MIN, LEASE_MAX, LEASE_DEFAULT = 600, 86400, 7200
MAX_PLACEMENTS_DEFAULT, MAX_PLACEMENTS_MAX = 8, 1000
WINDOW_MIN, WINDOW_MAX, WINDOW_DEFAULT = 5, 1440, 60  # takeover_window_minutes (§6.19)
FIELDS = (
    "preset",
    *CHOICES,
    "contract_arbiter",
    "lease_seconds",
    "max_placements",
    "coordinator",
    "coordinator_substitute",
    "jour_fixe",
    "jour_fixe_moderators",
    "takeover_window_minutes",
)
# Kept when a preset changes: a preset must not quietly loosen signing or who may start
# agents, reset the placement limit, the coordinator seats or the takeover window, or
# publish a badge or the swarm; only the field itself changes them (§6.1).
KEPT_ON_PRESET = (
    "signing",
    "spawn_requests",
    "spawn_consent_by",
    "max_placements",
    "coordinator",
    "coordinator_substitute",
    "on_runner_revoke",
    "badge",
    "subtasks",
    "swarm_public",
    "keep_the_why",
    "keep_the_why_defaults",
    "jour_fixe",
    "jour_fixe_moderators",
    "takeover_window_minutes",
)


def keep_the_why_effective(project: Any) -> str:
    """`required` or `optional` (§6.23): what a human set, else `required` under the
    provider `keep-the-why`; under `none` always `optional`."""
    if not project.keep_the_why:
        return "optional"
    return str(project.keep_the_why_policy or "required")


def filled(preset: str, owner_id: str) -> dict[str, Any]:
    policy = {
        "preset": preset,
        **_FILLINGS[preset],
        "lease_seconds": LEASE_DEFAULT,
        "max_placements": MAX_PLACEMENTS_DEFAULT,
        "coordinator": "role:admin",
        "coordinator_substitute": None,
        "on_runner_revoke": "inherit",
        "badge": "off",
        "subtasks": "proposed",
        "swarm_public": "off",
        "keep_the_why": None,  # nobody set it: it follows the memory provider
        "keep_the_why_defaults": "adopt",
        "jour_fixe": None,
        "jour_fixe_moderators": None,
        "takeover_window_minutes": WINDOW_DEFAULT,
    }
    if preset == "solo":
        policy["contract_arbiter"] = owner_id
    return policy


def of(project: Any) -> dict[str, Any]:
    """The policy object of a project row, in the contract's field order."""
    return {
        "preset": project.policy_preset,
        "claim_policy": project.claim_policy,
        "done_authority": project.done_authority,
        "contract_arbiter": project.contract_arbiter,
        "tag_authority": project.tag_authority,
        "steward_writes": project.steward_writes,
        "lease_seconds": project.lease_seconds,
        "signing": project.signing,
        "spawn_requests": project.spawn_requests,
        "spawn_consent_by": project.spawn_consent_by,
        "max_placements": project.max_placements,
        "coordinator": project.coordinator,
        "coordinator_substitute": project.coordinator_substitute,
        "on_runner_revoke": project.on_runner_revoke,
        "badge": getattr(project, "badge", "off"),
        "subtasks": getattr(project, "subtasks", "proposed"),
        "swarm_public": getattr(project, "swarm_public", "off"),
        "keep_the_why": keep_the_why_effective(project),
        "keep_the_why_defaults": project.keep_the_why_defaults,
        "jour_fixe": project.jour_fixe,
        "jour_fixe_moderators": project.jour_fixe_moderators,
        "takeover_window_minutes": project.takeover_window_minutes,
    }


def columns(policy: dict[str, Any]) -> dict[str, Any]:
    """The project columns of a policy object. `keep_the_why_policy` is not one of them:
    the object holds the effective value, and only a human's own setting is stored.
    """
    return {
        "policy_preset": policy["preset"],
        "claim_policy": policy["claim_policy"],
        "done_authority": policy["done_authority"],
        "contract_arbiter": policy["contract_arbiter"],
        "tag_authority": policy["tag_authority"],
        "steward_writes": policy["steward_writes"],
        "lease_seconds": policy["lease_seconds"],
        "signing": policy["signing"],
        "spawn_requests": policy["spawn_requests"],
        "spawn_consent_by": policy["spawn_consent_by"],
        "max_placements": policy["max_placements"],
        "coordinator": policy["coordinator"],
        "coordinator_substitute": policy["coordinator_substitute"],
        "on_runner_revoke": policy["on_runner_revoke"],
        "badge": policy["badge"],
        "subtasks": policy["subtasks"],
        "swarm_public": policy["swarm_public"],
        "keep_the_why_defaults": policy["keep_the_why_defaults"],
        "jour_fixe": policy["jour_fixe"],
        "jour_fixe_moderators": policy["jour_fixe_moderators"],
        "takeover_window_minutes": policy["takeover_window_minutes"],
    }


INSTANCE_RULES = ("keep", "stop", "stop_floor")


def runner_revoke_rule(project: Any, instance_rule: str) -> str:
    """`keep` or `stop`: the project's `on_runner_revoke` within the instance setting
    (§15.3). `inherit` takes the setting; `stop_floor` means stop whatever the project
    says, as a project's `keep` is refused under it."""
    if instance_rule == "stop_floor":
        return "stop"
    if project.on_runner_revoke == "inherit":
        return instance_rule
    rule: str = project.on_runner_revoke
    return rule
