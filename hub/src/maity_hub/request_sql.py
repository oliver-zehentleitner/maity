"""The one SQL copy of who sees which project request (docs/api.md §7), for the requests the
rules decide from plain columns: the "plain" ones (`plain`). Everything else is read with only
the columns the Python rules need (`DECIDED_BY`) and decided by those rules, unchanged.

Each helper names its Python twin, and the twin names it back: a change on one side is a change
on the other. `routes/overview.py` counts with these, `routes/requests.py` pages with them, and
both are tested against `routes/requests.py` `_filtered`, the readable rule."""

from __future__ import annotations

from sqlalchemy import ColumnElement, and_, or_, true

from maity_hub import inbox
from maity_hub import tables as t
from maity_hub.access import Membership
from maity_hub.scopes import tokens_of

# What `relayed`, `listed_to_all` and `inbox.addressed_to` read of a request, and the counts.
DECIDED_BY = (
    "id", "priority", "created_at", "personal", "to_kind", "to_member", "to_role",
    "holder_member", "holder_pool", "held", "cover", "jour_fixe", "proposal", "filed_by",
    "asked_by", "on_behalf_of",
)  # fmt: skip


def plain(mine: Membership) -> list[ColumnElement[bool]]:
    """The requests the helpers below decide for this caller: no `held` and no `cover` (a JSON
    list or object decides those, `inbox.held_back`, `inbox.covers`) and, where they change the
    answer, no `jour_fixe` for a holder of `requests:answer` (an owner's round opens to no
    scope: `inbox.owners_alone`, read from another table) and no `proposal` for a proxy
    (`routes/requests.py` `relayed`, by the proposal's kind)."""
    r = t.request.c
    found: list[ColumnElement[bool]] = [r.held.is_(None), r.cover.is_(None)]
    if mine.may("requests:answer"):
        found.append(r.jour_fixe.is_(None))
    if mine.role_base == "proxy":
        found.append(r.proposal.is_(None))
    return found


def in_own_right(mine: Membership) -> ColumnElement[bool]:
    """`inbox._in_own_right`: `to` names the caller's member id, the owner for an owner, or a
    token the caller holds. A change there is a change here."""
    r = t.request.c
    tokens = sorted(tokens_of(mine.trust, mine.role, mine.role_base))
    own_right = [
        and_(r.to_kind == "member", r.to_member == mine.id),
        and_(r.to_kind.not_in(("member", "owner")), r.to_role.in_(tokens)),
    ]
    if mine.trust == "owner":
        own_right.append(r.to_kind == "owner")
    return or_(*own_right)


def addressed(mine: Membership) -> ColumnElement[bool]:
    """`inbox.addressed_to` in plain columns, for a request that is not personal and has no
    `held` and no `cover` (the caller's `where` sees to that): its holder, the admins'
    pool for an admin, else `to` in the caller's own right (`in_own_right`). A change
    there is a change here."""
    r = t.request.c
    tokens = sorted(tokens_of(mine.trust, mine.role, mine.role_base))
    not_forwarded = and_(
        r.holder_member.is_(None), or_(r.holder_pool.is_(None), r.holder_pool.is_(False))
    )
    held_now = [r.holder_member == mine.id, and_(not_forwarded, in_own_right(mine))]
    if "trust:admin" in tokens:
        held_now.append(and_(r.holder_member.is_(None), r.holder_pool.is_(True)))
    return or_(*held_now)


def asked(mine: Membership) -> ColumnElement[bool]:
    """`inbox.is_asker`: the caller asked, or it was asked for, and the hub did not file it."""
    r = t.request.c
    return and_(
        or_(r.filed_by.is_(None), r.filed_by != "hub"),
        or_(r.asked_by == mine.id, r.on_behalf_of == mine.id),
    )


def listed_to_all(mine: Membership) -> list[ColumnElement[bool]]:
    """`routes/requests.py` `listed_to_all` for a plain request: a holder of
    `requests:answer` sees every one (no `jour_fixe`, so no owner's round), anyone else what
    it asked and what is addressed to it. Empty: no condition."""
    if mine.may("requests:answer"):
        return []
    return [or_(asked(mine), addressed(mine))]


def may_read(mine: Membership) -> ColumnElement[bool]:
    """`inbox.may_read` for a plain request: a holder of `requests:answer` (no owner's
    round), the asker, the holder now or `to` in the caller's own right (no cover)."""
    if mine.may("requests:answer"):
        return true()
    return or_(asked(mine), addressed(mine), in_own_right(mine))


def addressed_as(target: inbox.Addressee, whole_team: bool) -> ColumnElement[bool]:
    """`inbox.addressee_of(row) == target` (`routes/requests.py` `_filtered`), every field of
    the address compared; `whole_team` leaves the instance out, as `_filtered` does for a
    member id alone."""
    r = t.request.c
    fields = {
        "to_kind": target.kind,
        "to_member": target.member,
        "to_role": target.role,
        "to_profile": target.profile,
        "to_human": target.human,
    }
    if not whole_team:
        fields["to_instance"] = target.instance
    same = [r[name].is_(None) if v is None else r[name] == v for name, v in fields.items()]
    return and_(*same)
