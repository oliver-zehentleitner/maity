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

from sqlalchemy import Connection, String, cast, select, update

from maity_hub import events, inbox, moderation, namespace, org_projects, orgs, proposals, ticker
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


def withdraw_into(conn: Connection, org_id: str, reason: str) -> None:
    """Withdraw every open transfer into the organisation, whichever project it moves (§6.26,
    §16.8): its suspension and its deletion end them. The organisation's row is locked by the
    caller, before the projects' (`lock_project`) as everywhere."""
    from maity_hub.routes.requests import close_request

    rows = conn.execute(
        select(t.request.c.id, t.request.c.project_id, t.request.c.proposal)
        .where(
            t.request.c.status == "open",
            t.request.c.proposal.is_not(None),
            cast(t.request.c.proposal, String).contains(org_id, autoescape=True),
        )
        .order_by(t.request.c.created_at, t.request.c.id)
    ).all()
    for row in rows:
        proposal = row.proposal or {}
        if proposal.get("kind") != KIND or proposal.get("to") != org_id:
            continue
        events.lock_project(conn, row.project_id)
        close_request(conn, row.id, "withdrawn", None, reason=reason)


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


def _authority(conn: Connection, mine: Membership) -> None:
    """Who transfers a project: its namespace owner, a human; for a project of an organisation
    any owner of it (§6.25, §6.26)."""
    project = mine.project
    if mine.kind != "human":
        raise humans_only("a project is transferred by a human")
    if project.owner_org_id is not None:
        if orgs.role_of(conn, project.owner_org_id, mine.row.human_id) != "owner":
            raise orgs.org_role()
    elif mine.row.human_id != project.owner_id:
        raise forbidden(message="only the project's namespace owner transfers it")


def transfer(conn: Connection, mine: Membership, caller: Caller, to: str) -> str | None:
    """File the transfer to `to`, a human (`hum-…`) or an organisation (`org-…`); returns
    the request's id, or None when the move happened in the call itself (an owner of the
    receiving organisation speaks for it, an owner who hands a project of theirs organisation
    to themselves needs no request). §2.8.4 lists this call for the step-up; a hub without the
    second factor asks for none, as for every human not enrolled."""
    project = mine.project
    _authority(conn, mine)
    if to == project.owner_id:
        raise invalid({"to": "self"}, "the project is in this namespace already")
    if to.startswith("org-"):
        return _transfer_to_org(conn, mine, caller, to)
    receiver = _receiver(conn, project.id, to)
    if receiver is None:
        raise invalid({"to": "not_an_owner"}, "the receiver must be an owner of the project")
    namespace.check_change(conn, project, to, project.slug)
    actor = caller.actor(mine.id)
    if project.owner_org_id is not None and mine.row.human_id == to:
        # An owner of the organisation hands the project to themselves: their call is their word.
        withdraw_open(conn, project.id, actor, "a new transfer was filed")
        move_to(conn, project, to, actor, mine.principal_id)
        return None
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


def _transfer_to_org(conn: Connection, mine: Membership, caller: Caller, org_id: str) -> str | None:
    """A transfer into an organisation (§6.26): an `owner` of it speaks for it and the move
    happens now; an `admin` speaks only for themselves, and a consent request goes to each
    owner of the organisation, the first `go` moving the project."""
    project = mine.project
    me = mine.row.human_id
    org = orgs.lock(conn, org_id)  # the route locked it already, before the project
    role = orgs.role_of(conn, org_id, me) if org is not None else None
    if org is None or role is None:
        raise invalid({"to": "unknown"}, "no such organisation")
    if role == "member":
        raise orgs.org_role()
    moderation.refuse_held(conn, "org", org_id, "suspend")  # §16.8: nothing moves into it
    namespace.check_change(conn, project, org_id, project.slug)
    actor = caller.actor(mine.id)
    withdraw_open(conn, project.id, actor, "a new transfer was filed")
    if role == "owner":
        move_to(conn, project, org_id, actor, mine.principal_id)
        return None
    from maity_hub.routes.requests import file_org_consent

    full = namespace.full_name(conn, project)
    proposal = {
        "kind": KIND,
        "project_id": project.id,
        "owner_id": project.owner_id,
        "full_name": full,
        "to": org_id,
        "by": me,
    }
    first = None
    for owner_id in org_projects.owners_of(conn, org_id):
        request_id = file_org_consent(
            conn,
            mine,
            caller,
            f"Take over {full} into {org.handle}",
            _org_summary(mine.principal_id, full, org.handle, project.repository_url),
            proposal,
            to_human=owner_id,
            org_id=org_id,
        )
        first = first or request_id
    assert first is not None  # an organisation has an owner
    return first


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


def _org_summary(asker: str, full: str, org: str, repository_url: str | None) -> str:
    """The consent request to an owner of the receiving organisation: it names the repository
    and says that the project is not public under the new name until they say so."""
    text = f"{asker} asks you to take {full} into the organisation {org}."
    if repository_url is not None:
        text += f" Its repository is {repository_url}; forge access applies only once confirmed."
    return text + " The project's public page is turned off by the move."


def move_to(conn: Connection, project: Any, to: str, actor: Actor | None, by: str | None) -> None:
    """Move the project to the namespace owner `to` (a human or an organisation), with
    everything §6.25 and §6.26 say that goes with it: the old name an alias, the repository
    no longer confirmed, the memberships the hub kept for the sending organisation's owners
    ended and the receiving organisation's owners made owners, `project_updated` and the
    ticker's `rename`. `check_change` came first."""
    old_full = namespace.full_name(conn, project)
    sending = project.owner_org_id
    namespace.move(conn, project, to, project.slug)
    conn.execute(
        update(t.project)
        .where(t.project.c.id == project.id)
        .values(repository_owner_confirmed=False)
    )
    moved = conn.execute(select(t.project).where(t.project.c.id == project.id)).one()
    org_projects.moved(
        conn, moved, sending, moved.owner_org_id, to if to.startswith("hum-") else None
    )
    owner = namespace.owner_of(conn, moved)
    _announce(conn, project.id, old_full, {"owner": owner}, actor, by)


def _stale(request_id: str, message: str) -> proposals.Stale:
    error = ApiError(409, "invalid_transition", message, {"reason": "transfer_stale"})
    return proposals.Stale(error, request_id, "the transfer is stale")


def settle(conn: Connection, s: proposals.Settlement) -> None:
    """Move the project on `go`, when nothing it was bound to changed; `no` and a
    withdrawal change nothing, except that the withdrawal by the human who started a
    transfer into an organisation withdraws every request of it (§6.26)."""
    proposal, request = s.proposal, s.request
    if s.outcome == "withdrawn":
        _withdraw_siblings(conn, s)
        return
    if s.outcome != "go":
        return
    to = proposal["to"]
    org = (
        orgs.lock(conn, to) if to.startswith("org-") else None
    )  # the organisation, then the project (§6.26)
    events.lock_project(conn, proposal["project_id"])
    project = conn.execute(select(t.project).where(t.project.c.id == proposal["project_id"])).one()
    full = namespace.full_name(conn, project)
    if project.owner_id != proposal["owner_id"] or full != proposal["full_name"]:
        raise _stale(request.id, "the project's owner or name changed since the transfer")
    if to.startswith("org-"):
        _check_org_go(conn, s, org)
    elif _receiver(conn, project.id, to) is None:
        raise _stale(request.id, "the receiver is no owner of the project any more")
    if namespace.taken(conn, to, project.slug, project.id):
        taken = invalid({"slug": "taken"}, "the slug is taken in the receiver's namespace")
        raise proposals.Stale(taken, request.id, "the slug is taken in the receiver's namespace")
    namespace.check_change(conn, project, to, project.slug)
    move_to(conn, project, to, s.closer, s.approver)
    if to.startswith("org-"):  # the first owner's go moves it: the other requests are withdrawn
        withdraw_open(conn, project.id, s.closer, "another owner of the organisation said go")


def _check_org_go(conn: Connection, s: proposals.Settlement, org: Any) -> None:
    """The `go` into an organisation holds only while it is not deleted, its answerer is still
    an owner and the one who started the transfer still an owner or admin of it. `org` is the
    row `settle` locked before the project's."""
    request, proposal = s.request, s.proposal
    org_id = proposal["to"]
    if org is None:
        raise _stale(request.id, "the organisation was deleted")
    moderation.refuse_held(conn, "org", org_id, "suspend")  # a `go` stays open, not stale
    if orgs.role_of(conn, org_id, s.approver or "") != "owner":
        raise _stale(request.id, "the answerer is no owner of the organisation any more")
    if orgs.role_of(conn, org_id, proposal.get("by", "")) not in ("owner", "admin"):
        raise _stale(request.id, "the one who started the transfer lost their role")


def _withdraw_siblings(conn: Connection, s: proposals.Settlement) -> None:
    """The human who started a transfer into an organisation withdraws all its requests; an
    owner's own withdrawal counts as their `no` and closes theirs alone (§6.26)."""
    if not s.proposal["to"].startswith("org-"):
        return
    closer = s.closer.membership_id if s.closer is not None else None
    if closer is None or closer != s.request.asked_by:
        return
    withdraw_open(conn, s.proposal["project_id"], s.closer, "the transfer was withdrawn")


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
