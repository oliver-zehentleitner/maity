"""Changes that wait for a human's go (docs/api.md §2.3 ᵃ, §19.2, and the slices that
reuse it).

A proposal is a `consent` request to `owner` that carries what to do once it is
answered: `request.proposal = {"kind": <kind>, ...}`. Each kind registers how it is
settled, who may answer it, and optionally what its request shows. `routes/requests.py`
calls `settle` wherever a request closes — an answer, a withdrawal, and every close the
hub makes itself (`close_request`) — and `inbox` asks `answerer` before offering or
accepting an answer, so a new kind needs neither its own column nor its own branch in
the routes. A kind the hub does not know fails loud on that request only: its answer
and withdrawal are refused, and no list or resume packet offers it.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Connection

from maity_hub.errors import ApiError
from maity_hub.events import Actor


@dataclass(frozen=True)
class Settlement:
    """What a kind's `settle` is told: the request, its proposal and how it closed."""

    request: Any  # the request row
    proposal: dict[str, Any]
    outcome: str  # go, no (any other answer), withdrawn
    proposer: Actor  # the membership and session that asked: the change's actor
    approver: str | None  # the answering principal on go and no; None when withdrawn
    closer: Actor | None  # who closed it: the answerer, the withdrawer, or the hub's actor
    # The reply chosen, for a kind whose options are more than go and no (§6.19's
    # `transfer` and `keep`); None when withdrawn or answered by text.
    reply_id: str | None = None


# A kind's own rule on who answers, beyond the scope: a `details.reason` for a caller it
# refuses (`party_to_takeover`, `admin_team_only`), None for one it lets answer.
Predicate = Callable[[Connection, Any, Any], str | None]


@dataclass(frozen=True)
class Answerer:
    """Who may answer a kind's request: a holder of `scope`, and only a human when
    `humans_only` (an agent is refused with `details.reason: humans_only`). `predicate`
    narrows it further for the kind and is asked wherever the scope is; `reply_required`
    refuses an answer by text alone."""

    scope: str = "requests:answer"
    humans_only: bool = True
    refusal: str = "only a human answers this"
    predicate: Predicate | None = None
    reply_required: bool = False


Settle = Callable[[Connection, Settlement], None]
# The kind's own fields in `GET …/requests/{id}`, never in an event, a list or a resume
# packet: only what every reader of the request may see, never a key the view has.
View = Callable[[Connection, Any, dict[str, Any]], dict[str, Any]]


@dataclass(frozen=True)
class Kind:
    settle: Settle
    answerer: Answerer
    view: View | None


KINDS: dict[str, Kind] = {}


def register(name: str, settle: Settle, answerer: Answerer, *, view: View | None = None) -> None:
    if name in KINDS:  # a second registration would silently change who may answer
        raise ValueError(f"proposal kind {name!r} is registered already")
    KINDS[name] = Kind(settle, answerer, view)


def of(request: Any) -> dict[str, Any] | None:
    """The request's proposal, or None for an ordinary request."""
    proposal: dict[str, Any] | None = request.proposal
    return proposal


def known(request: Any) -> bool:
    proposal = of(request)
    return proposal is None or proposal.get("kind") in KINDS


def _kind(request: Any) -> Kind:
    proposal = of(request)
    assert proposal is not None
    kind = KINDS.get(str(proposal.get("kind")))
    if kind is None:
        raise ApiError(
            500,
            "proposal_kind_unknown",
            f"request {request.id} carries a proposal of a kind this hub does not know",
            {"kind": proposal.get("kind")},
        )
    return kind


def answerer(request: Any) -> Answerer | None:
    """The kind's answerer rule, or None for an ordinary request or an unknown kind."""
    if of(request) is None or not known(request):
        return None
    return _kind(request).answerer


def refusal(conn: Connection, request: Any, mine: Any) -> str | None:
    """The kind's predicate on this caller: a `details.reason` when it refuses, else None."""
    rule = answerer(request)
    if rule is None or rule.predicate is None:
        return None
    return rule.predicate(conn, request, mine)


def check_kind(proposal: dict[str, Any]) -> None:
    """At filing time: only a registered kind is stored."""
    if proposal.get("kind") not in KINDS:
        raise ValueError(f"proposal kind {proposal.get('kind')!r} is not registered")


def require_known(request: Any) -> None:
    """Before an answer or a withdrawal: an unknown kind fails loud on this request."""
    if of(request) is not None:
        _kind(request)


def view(conn: Connection, request: Any) -> dict[str, Any]:
    proposal = of(request)
    if proposal is None or not known(request):
        return {}
    shown = _kind(request).view
    return shown(conn, request, proposal) if shown is not None else {}


def settle(
    conn: Connection,
    request: Any,
    outcome: str,
    approver: str | None,
    closer: Actor | None,
    *,
    reply_id: str | None = None,
) -> None:
    """Settle the request's proposal, if it carries one, in the caller's transaction."""
    proposal = of(request)
    if proposal is None:
        return
    proposer = Actor(request.asked_by, request.asked_session_id)
    _kind(request).settle(
        conn, Settlement(request, proposal, outcome, proposer, approver, closer, reply_id)
    )
