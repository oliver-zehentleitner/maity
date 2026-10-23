"""Changes that wait for a human's go (docs/api.md §2.3 ᵃ, and the slices that reuse it).

A proposal is a `consent` request to `owner` that carries what to do once it is
answered: `request.proposal = {"kind": <kind>, ...}`. Each kind registers how it is
settled (`go`, `no` for any other answer, or `withdrawn`) and whether only a human may
answer it. `routes/requests.py` calls `settle` once, next to the placements' own, and
`inbox.needs_a_human` asks `humans_only` — so a new kind needs neither its own column
nor its own branch in the answer route.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Connection

from maity_hub.events import Actor

Settle = Callable[[Connection, Any, dict[str, Any], str, Actor | None, str | None], None]


@dataclass(frozen=True)
class Kind:
    settle: Settle  # (conn, request row, proposal, outcome, actor, by principal)
    humans_only: bool  # an agent's answer is forbidden (details.reason: humans_only)


KINDS: dict[str, Kind] = {}


def register(name: str, settle: Settle, *, humans_only: bool) -> None:
    KINDS[name] = Kind(settle, humans_only)


def of(request: Any) -> dict[str, Any] | None:
    """The request's proposal, or None for an ordinary request."""
    proposal: dict[str, Any] | None = getattr(request, "proposal", None)
    return proposal


def humans_only(request: Any) -> bool:
    proposal = of(request)
    return proposal is not None and KINDS[proposal["kind"]].humans_only


def settle(
    conn: Connection, request: Any, outcome: str, actor: Actor | None, by: str | None
) -> None:
    """Settle the request's proposal, if it carries one, in the caller's transaction."""
    proposal = of(request)
    if proposal is not None:
        KINDS[proposal["kind"]].settle(conn, request, proposal, outcome, actor, by)
