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
}
LEASE_MIN, LEASE_MAX, LEASE_DEFAULT = 600, 86400, 7200
FIELDS = ("preset", *CHOICES, "contract_arbiter", "lease_seconds")


def filled(preset: str, owner_id: str) -> dict[str, Any]:
    policy = {"preset": preset, **_FILLINGS[preset], "lease_seconds": LEASE_DEFAULT}
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
    }


def columns(policy: dict[str, Any]) -> dict[str, Any]:
    """The project columns of a policy object."""
    return {
        "policy_preset": policy["preset"],
        "claim_policy": policy["claim_policy"],
        "done_authority": policy["done_authority"],
        "contract_arbiter": policy["contract_arbiter"],
        "tag_authority": policy["tag_authority"],
        "steward_writes": policy["steward_writes"],
        "lease_seconds": policy["lease_seconds"],
        "signing": policy["signing"],
    }
