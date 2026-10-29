"""A project's rename and transfer (docs/api.md §6.25).

A rename (`PATCH /projects/{owner}/{slug}` with `slug`) and a transfer to another
namespace owner both give the project a new full name; the name given up becomes an
alias (`namespace.move`). A transfer waits for the receiver's word: it is a
`project_transfer` proposal (`proposals`), a consent request to the receiver that is
bound to the project's id, namespace owner and full name at filing. Every change of
the owner or the name withdraws the open transfer, so the `go` finds them changed only
through a race; it checks them again, with the receiver's trust and the slug, in the
transaction of the move, and a stale `go` withdraws the request (`proposals.Stale`).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Connection, select, update

from maity_hub import events, inbox, namespace, proposals, ticker
from maity_hub import tables as t
from maity_hub.access import Membership
from maity_hub.auth.caller import Caller
from maity_hub.errors import ApiError, forbidden, humans_only, invalid
from maity_hub.events import Actor, emit

KIND = "project_transfer"


def open_transfers(conn: Connection, project_id: str) -> list[Any]:
    rows = conn.execute(
        select(t.request).where(
            t.request.c.project_id == project_id,
            t.request.c.status == "open",
            t.request.c.proposal.is_not(None),
        )
    ).all()
    return [row for row in rows if (row.proposal or {}).get("kind") == KIND]


def withdraw_open(conn: Connection, project_id: str, actor: Actor | None, reason: str) -> None:
    """A project has at most one open transfer; a change of its owner or name, or a new
    transfer, withdraws it (§6.25)."""
    from maity_hub.routes.requests import close_request

    for row in open_transfers(conn, project_id):
        close_request(conn, row.id, "withdrawn", actor, reason=reason)


def _announce(
    conn: Connection,
    project_id: str,
    old: str,
    fields: dict[str, Any],
    actor: Actor | None,
    by: str | None,
) -> None:
    """`project_updated` with the changed fields and the ticker's `rename` item (§6.25)."""
    new = namespace.name_of(conn, project_id)
    emit(
        conn,
        project_id,
        "project_updated",
        ["all"],
        {"fields": {**fields, "full_name": new}},
        actor=actor,
        subject=("project", new),
    )
    ticker.write_rename(conn, project_id, old, new, actor, by)


def rename(
    conn: Connection,
    mine: Membership,
    slug: str,
    words: frozenset[str],
    actor: Actor,
) -> bool:
    """Rename the project to `slug` in its namespace; False for a no-op. By a human with
    trust `owner`, never an agent."""
    project = mine.project
    if mine.kind != "human":
        raise humans_only("a project is renamed by a human")
    if mine.trust != "owner":
        raise forbidden(message="a project is renamed by an owner")
    if slug == project.slug:
        return False
    if slug in words:
        raise invalid({"slug": "reserved"}, "this slug is a word of the API's routes")
    namespace.check_change(conn, project, project.owner_id, slug)
    old = namespace.full_name(conn, project)
    withdraw_open(conn, project.id, actor, "the project was renamed")
    namespace.move(conn, project, project.owner_id, slug)
    _announce(conn, project.id, old, {"slug": slug}, actor, mine.principal_id)
    return True


def _receiver(conn: Connection, project_id: str, human_id: str) -> Any:
    """The receiver's active membership with trust `owner`, or None."""
    return conn.execute(
        select(t.membership).where(
            t.membership.c.project_id == project_id,
            t.membership.c.human_id == human_id,
            t.membership.c.trust == "owner",
            t.membership.c.active.is_(True),
        )
    ).first()


def transfer(conn: Connection, mine: Membership, caller: Caller, to: str) -> str:
    """File the transfer to the human `to`; returns the request's id. By the namespace
    owner only. §2.8.4 lists this call for the step-up; a hub without the second factor
    asks for none, as for every human not enrolled."""
    project = mine.project
    if mine.kind != "human":
        raise humans_only("a project is transferred by a human")
    if mine.row.human_id != project.owner_id:
        raise forbidden(message="only the project's namespace owner transfers it")
    if to == project.owner_id:
        raise invalid({"to": "self"}, "the project is in this namespace already")
    receiver = _receiver(conn, project.id, to)
    if receiver is None:
        raise invalid({"to": "not_an_owner"}, "the receiver must be an owner of the project")
    namespace.check_change(conn, project, to, project.slug)
    actor = caller.actor(mine.id)
    withdraw_open(conn, project.id, actor, "a new transfer was filed")
    from maity_hub.routes.requests import file_proposal

    full = namespace.full_name(conn, project)
    handle = conn.execute(select(t.human.c.handle).where(t.human.c.id == to)).scalar_one()
    proposal = {
        "kind": KIND,
        "project_id": project.id,
        "owner_id": project.owner_id,
        "full_name": full,
        "to": to,
    }
    return file_proposal(
        conn,
        project.id,
        mine.id,
        "consent",
        f"Take over {full} as {handle}/{project.slug}",
        _summary(mine.principal_id, full, project.repository_url),
        proposal,
        to=inbox.Addressee("member", member=receiver.id),
        options=[],
        while_open="wait",
        actor=actor,
    )


def _summary(asker: str, full: str, repository_url: str | None) -> str:
    """The consent request's text. It names the repository, so the receiver sees what
    confirming it for their own forge access would grant (§11.4)."""
    text = f"{asker} asks you to become the namespace owner of {full}."
    if repository_url is not None:
        text += (
            f" Its repository is {repository_url}; your forge access applies to it"
            " only once you confirm it."
        )
    return text


def _stale(request_id: str, message: str) -> proposals.Stale:
    error = ApiError(409, "invalid_transition", message, {"reason": "transfer_stale"})
    return proposals.Stale(error, request_id, "the transfer is stale")


def settle(conn: Connection, s: proposals.Settlement) -> None:
    """Move the project on `go`, when nothing it was bound to changed; `no` and a
    withdrawal change nothing."""
    if s.outcome != "go":
        return
    proposal, request = s.proposal, s.request
    events.lock_project(conn, proposal["project_id"])
    project = conn.execute(select(t.project).where(t.project.c.id == proposal["project_id"])).one()
    full = namespace.full_name(conn, project)
    if project.owner_id != proposal["owner_id"] or full != proposal["full_name"]:
        raise _stale(request.id, "the project's owner or name changed since the transfer")
    if _receiver(conn, project.id, proposal["to"]) is None:
        raise _stale(request.id, "the receiver is no owner of the project any more")
    if namespace.taken(conn, proposal["to"], project.slug, project.id):
        taken = invalid({"slug": "taken"}, "the slug is taken in the receiver's namespace")
        raise proposals.Stale(taken, request.id, "the slug is taken in the receiver's namespace")
    namespace.check_change(conn, project, proposal["to"], project.slug)
    namespace.move(conn, project, proposal["to"], project.slug)
    # The old owner confirmed the repository for their grants; the new owner's apply
    # only once they confirm it themselves (§11.4).
    conn.execute(
        update(t.project)
        .where(t.project.c.id == project.id)
        .values(repository_owner_confirmed=False)
    )
    owner = namespace.owner_of(
        conn, conn.execute(select(t.project).where(t.project.c.id == project.id)).one()
    )
    _announce(conn, project.id, full, {"owner": owner}, s.closer, s.approver)


def _the_receiver(conn: Connection, request: Any, mine: Any) -> str | None:
    """Only the receiver answers: nothing moves into a namespace without its owner."""
    proposal = proposals.of(request) or {}
    return None if mine.row.human_id == proposal.get("to") else "not_the_receiver"


proposals.register(
    KIND,
    settle,
    proposals.Answerer(
        refusal="the receiver answers a transfer",
        predicate=_the_receiver,
    ),
)
