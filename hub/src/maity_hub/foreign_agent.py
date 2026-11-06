"""Another owner's agent changes only with its owner's consent (docs/api.md §6.2, "Another
owner's agent").

A `PATCH` of an agent member by a caller that is neither the agent's owner nor one of that
owner's agents nor a manager inside its reach does not change `trust`, `role`, `reports_to`,
`areas`, `capabilities`, `briefing`, `paused` or `availability_policy` on the call. A
`reports_to` that crosses owners stays the two-owner pair and is not also a field of this
request. The hub files one `consent` request, a personal request to the owner
(`to: human:<id>`, §7), `asked_by` the caller, and applies the stored values at `go` as one
`member_updated`, the owner as approver and the caller as actor. A `no` or a withdrawal changes
nothing; a further `PATCH` of the member by such a caller withdraws the open request
(`superseded`) and files a new one for the fields it names.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Connection, select, update

from maity_hub import (
    admin_agents,
    agent_owners,
    availability,
    cross_owner,
    instances,
    jcs,
    namespace,
    project_roles,
    proposals,
)
from maity_hub import tables as t
from maity_hub.access import Membership
from maity_hub.auth.caller import Caller
from maity_hub.errors import ApiError, invalid
from maity_hub.events import Actor, lock_project
from maity_hub.scopes import has_scope, in_admin_team
from maity_hub.views import principal_id

KIND = "foreign_agent_change"
# `role_base` goes with `role` (a role change sets both, §2.3): it waits for the owner too, but
# the summary and `agent_change` name the role only. `reports_to` waits here unless the edge
# crosses owners, in which case the pair holds it and this request does not.
FIELDS = (
    "trust",
    "role",
    "role_base",
    "areas",
    "capabilities",
    "briefing",
    "availability_policy",
    "dormant",
)
# The summary and `agent_change` name fields in this order, and only the ones the request carries.
ORDER = (
    "trust",
    "role",
    "reports_to",
    "areas",
    "capabilities",
    "briefing",
    "paused",
    "availability_policy",
    "dormant",
)
# A raw JSON field whose tokens are checked before a model coerces a number. `dormant` is the
# one boolean; a `true` anywhere else is not an integer token.
TOKEN_FIELDS = frozenset(ORDER)
OMITTED = "full value in agent_change"
SUMMARY_CAP = 16384  # characters, the Markdown cap (§1.7)


def is_foreign(conn: Connection, who: Any, target: Any) -> bool:
    """The change needs the agent owner's consent: `target` is an agent and `who`, a
    membership row, is neither its owner nor one of that owner's agents."""
    if target.agent_id is None:
        return False
    return bool(cross_owner.owner_of(conn, who) != cross_owner.owner_of(conn, target))


def consented(values: dict[str, Any], pause: tuple[bool, str | None]) -> dict[str, Any]:
    """The fields of a change that wait for the owner. A cross-owner `reports_to` is not among
    them: the caller leaves it out (`for_consent`)."""
    wanted = {k: v for k, v in values.items() if k in FIELDS or k == "reports_to"}
    if pause[0]:
        wanted["paused"] = pause[1]
    return wanted


def for_consent(values: dict[str, Any], *, cross_reports_to: bool) -> dict[str, Any]:
    """The values the owner's request holds. A cross-owner `reports_to` stays on the pair."""
    held = {k: v for k, v in values.items() if k in FIELDS or k == "reports_to"}
    if cross_reports_to:
        held.pop("reports_to", None)
    return held


def without_consent(values: dict[str, Any], held: dict[str, Any]) -> dict[str, Any]:
    """What still applies on the call once `held` waits for the owner."""
    return {k: v for k, v in values.items() if k not in held}


def reject_tokens(raw: bytes) -> None:
    """Number and string tokens of the raw body, before a model reads `1.0` as `1`."""
    if not raw:
        return
    try:
        body = json.loads(raw)
    except json.JSONDecodeError:
        return
    if not isinstance(body, dict):
        return
    errors: dict[str, str] = {}
    for name in ORDER:
        if name not in body:
            continue
        try:
            jcs.check_tokens(body[name], bool_ok=name == "dormant")
        except jcs.CanonicalError as error:
            errors[name] = error.code
    if errors:
        raise invalid(errors)


def open_for(conn: Connection, target_id: int, besides: str | None = None) -> list[Any]:
    rows = conn.execute(
        select(t.request)
        .where(
            t.request.c.status == "open",
            t.request.c.proposal.is_not(None),
            t.request.c.personal.is_(True),
        )
        .order_by(t.request.c.created_at, t.request.c.id)
    ).all()
    return [
        r
        for r in rows
        if (r.proposal or {}).get("kind") == KIND
        and (r.proposal or {}).get("target") == target_id
        and r.id != besides
    ]


def withdraw_open(conn: Connection, target_id: int, actor: Actor | None, reason: str) -> None:
    """A newer `PATCH` (`superseded`) or the removal of the member (`member_removed`)."""
    from maity_hub.routes.requests import close_request

    for row in open_for(conn, target_id):
        close_request(conn, row.id, "withdrawn", actor, reason=reason)


def _quote(value: Any) -> str:
    """A value in the summary, in full: a string as itself, anything else in canonical form."""
    if isinstance(value, str):
        return value
    return jcs.canonicalize(value)


def _reports_to_text(conn: Connection, membership_id: int | None) -> str:
    """A `reports_to` value for the summary: the member id, and, unless it is null, that
    member's handle and the handle of the human who owns them."""
    if membership_id is None:
        return "null"
    row = conn.execute(select(t.membership).where(t.membership.c.id == membership_id)).one()
    handle = cross_owner._handle(conn, row)
    owner = cross_owner.owner_of(conn, row)
    owner_handle = cross_owner._human_handle(conn, owner) if owner is not None else handle
    public = principal_id(conn, membership_id)
    return f"{public} ({handle}, owner {owner_handle})"


def _credential(conn: Connection, membership_id: int, instance: str | None) -> Any:
    if instance is None:
        return None
    return conn.execute(
        select(t.credential).where(
            t.credential.c.membership_id == membership_id,
            t.credential.c.instance == instance,
            t.credential.c.revoked_at.is_(None),
        )
    ).first()


@dataclass
class _Piece:
    index: int
    proposed: bool
    text: str
    fixed: bool = False
    replaced: bool = False


def _fit(preamble: str, rows: list[tuple[str, _Piece, _Piece]], closing: str) -> str:
    """Quote every value in full while the summary stays within the cap. Past it, replace
    the longest still-quoted value other than `reports_to` with `OMITTED`, later fields
    first when the lengths match, and within a field the current value before the proposed."""

    def render() -> str:
        lines = [preamble]
        for label, current, proposed in rows:
            lines.append(f"- {label}: {current.text} → {proposed.text}")
        lines.append(closing)
        return "\n".join(lines)

    summary = render()
    while len(summary) > SUMMARY_CAP:
        candidates = [
            piece
            for _, current, proposed in rows
            for piece in (current, proposed)
            if not piece.fixed and not piece.replaced
        ]
        if not candidates:
            break
        chosen = max(
            candidates, key=lambda piece: (len(piece.text), piece.index, 0 if piece.proposed else 1)
        )
        if len(chosen.text) <= len(OMITTED):
            break
        chosen.text = OMITTED
        chosen.replaced = True
        summary = render()
    return summary


def _summary(
    conn: Connection,
    project: Any,
    asker: str,
    handle: str,
    target: Any,
    shown: dict[str, Any],
    reports_to_id: int | None,
    instance: str | None,
) -> str:
    """What the decision needs, all in the request: the current and the proposed value of
    each field, in full while the summary fits, for an owner who may not be a member."""
    preamble = (
        f"In the project {project.name} ({namespace.full_name(conn, project)}), {asker} asks "
        f"to change your agent {handle}:"
    )
    closing = "Nothing changes until you answer; a `no` or a withdrawal changes nothing."
    rows: list[tuple[str, _Piece, _Piece]] = []
    for index, name in enumerate(ORDER):
        if name not in shown:
            continue
        if name == "reports_to":
            rows.append(
                (
                    name,
                    _Piece(index, False, _reports_to_text(conn, target.reports_to), fixed=True),
                    _Piece(index, True, _reports_to_text(conn, reports_to_id), fixed=True),
                )
            )
            continue
        if name == "dormant":
            held = _credential(conn, target.id, instance)
            now = "dormant" if held is not None and held.dormant_since is not None else "awake"
            label = f"dormant (instance {instance})" if instance else "dormant"
            rows.append(
                (
                    label,
                    _Piece(index, False, now),
                    _Piece(index, True, "dormant" if shown[name] else "awake"),
                )
            )
            continue
        if name == "paused":
            current: Any = (
                target.paused_reason
                if instance is None and target.paused_since is not None
                else None
            )
            if instance is not None:
                cred = _credential(conn, target.id, instance)
                current = (
                    cred.paused_reason
                    if cred is not None and cred.paused_since is not None
                    else None
                )
        elif name == "availability_policy":
            current = availability.policy_of(target)
        else:
            current = getattr(target, name)
        rows.append(
            (name, _Piece(index, False, _quote(current)), _Piece(index, True, _quote(shown[name])))
        )
    return _fit(preamble, rows, closing)


def _hash(value: Any) -> tuple[str, str]:
    canonical = jcs.canonicalize(value)
    return canonical, hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def file(
    conn: Connection,
    project: Any,
    mine: Membership,
    caller: Caller,
    target: Any,
    values: dict[str, Any],
    pause: tuple[bool, str | None],
    instance: str | None,
) -> str | None:
    """File the owner's consent for `values` and `pause` of `target`; its id, or None when
    nothing in the change waits for the owner."""
    from maity_hub.routes.requests import file_to_human

    wanted = consented(values, pause)
    if not wanted:
        return None
    shown: dict[str, Any] = {}
    stored = {k: v for k, v in values.items() if k in FIELDS}
    reports_to_id: int | None = None
    if "reports_to" in wanted:
        raw = wanted["reports_to"]
        if raw is None:
            shown["reports_to"] = None
        else:
            reports_to_id = int(raw)
            public = principal_id(conn, reports_to_id)
            assert public is not None
            shown["reports_to"] = public
        stored["reports_to"] = shown["reports_to"]
    for name in ORDER:
        if name in ("reports_to", "role_base"):
            continue
        if name == "paused":
            if pause[0]:
                shown["paused"] = pause[1]
            continue
        if name in wanted:
            shown[name] = wanted[name]
    canonical: dict[str, str] = {}
    digest: dict[str, str] = {}
    for name, proposed in shown.items():
        try:
            text, hashed = _hash(proposed)
        except jcs.CanonicalError as error:
            raise invalid({name: error.code}) from None
        canonical[name] = text
        digest[name] = hashed
    owner = cross_owner.owner_of(conn, target)
    assert owner is not None
    handle = cross_owner._handle(conn, target)
    asker = cross_owner._handle(conn, mine.row)
    proposal = {
        "kind": KIND,
        "target": target.id,
        "values": stored,
        "canonical": canonical,
        "sha256": digest,
        "pause": [pause[0], pause[1]],
        "instance": instance,
    }
    return file_to_human(
        conn,
        mine,
        caller,
        owner,
        f"Change {handle} in {project.name}",
        _summary(conn, project, asker, handle, target, shown, reports_to_id, instance),
        proposal,
    )


def remember_pair(conn: Connection, request_id: str, pair: list[str]) -> None:
    """The cross-owner pair this change also filed, so a replay of the PATCH `202` lists the
    same ids. The request read and a replay of the owner's answer do not: only
    `load_member_patch`, which builds that `202`, adds them."""
    row = conn.execute(select(t.request).where(t.request.c.id == request_id)).one()
    conn.execute(
        update(t.request)
        .where(t.request.c.id == request_id)
        .values(proposal={**row.proposal, "cross_owner_reports_to": list(pair)})
    )


def _refuse(why: str) -> ApiError:
    return ApiError(409, "asker_not_allowed", why)


def _still_allowed(
    conn: Connection,
    asker: Any,
    project: Any,
    target: Any,
    values: dict[str, Any],
    pause: tuple[bool, str | None],
    instance: str | None,
) -> None:
    """The asker may still make this change: still an active member, not isolated, still
    holding `members:admin` (a human) or still an admin agent, by the role's base (a project's
    own role holds the scopes of its base), and the call's own checks hold against today's
    state: only an owner grants trust `owner` or `admin` or the role `proxy`, an admin agent
    stays within §2.3 ᵃ. Otherwise the `go` is refused and the request stays open, for a `no`
    or a withdrawal, as every other refusal at a `go` (§6.2)."""
    from maity_hub.routes import members

    if asker is None or asker.active is not True or asker.isolated_since is not None:
        raise _refuse("the one who asked may not change this member any more")
    agent = asker.agent_id is not None
    if agent and not in_admin_team(asker.trust, asker.role_base):
        raise _refuse("the one who asked is no admin agent any more")
    if not agent and not has_scope(asker.trust, asker.role_base, "human", "members:admin"):
        raise _refuse("the one who asked no longer holds members:admin")
    mine = Membership(project, asker, "agent" if agent else "human")
    try:
        members._require_owner_for_change(mine, target, values)
    except ApiError:
        raise _refuse("the one who asked may not grant this any more") from None
    if agent:
        try:
            admin_agents.check_change(
                mine,
                target,
                trust=values.get("trust"),
                role=values.get("role"),
                capabilities="capabilities" in values,
                pause=(bool(pause[0]), pause[1] is None),
            )
            if pause[0] and instance is not None:
                # One instance's pause: its own credential, as on the call (§5.3, §6.17).
                held = instances.require_active(conn, target, instance, "instance")
                admin_agents.check_instance_pause(held, asker.agent_id, pause[1] is None)
        except ApiError:
            raise _refuse("an admin agent does not make this change") from None


def settle(conn: Connection, s: proposals.Settlement) -> None:
    """Apply the whole change on `go`, the owner as approver and the asker as actor; `no` and a
    withdrawal change nothing (§6.2)."""
    from maity_hub.routes import members

    if s.outcome != "go" or s.approver is None:
        return
    proposal, request = s.proposal, s.request
    project = lock_project(conn, request.project_id)
    target = conn.execute(
        select(t.membership).where(t.membership.c.id == proposal["target"])
    ).first()
    if target is None or target.active is None:  # removed meanwhile: nothing left to change
        return
    asker = conn.execute(select(t.membership).where(t.membership.c.id == request.asked_by)).first()
    given, reason = proposal["pause"]
    values = dict(proposal["values"])
    if "role" in values:
        # The base of the role as the project has it now: a project role may have been rebased
        # or removed while the request waited (§2.3 "Project roles").
        base = project_roles.base_of(project, values["role"])
        if base is None:
            raise ApiError(409, "role_unknown", "the project has no such role any more")
        values["role_base"] = base
    agent_owners.check_assignment(conn, project, target, values)  # the limits as they are now
    _still_allowed(
        conn, asker, project, target, values, (bool(given), reason), proposal.get("instance")
    )
    assert asker is not None  # `_still_allowed` refuses a missing asker
    if "reports_to" in values:
        # The stored value is the member id the owner was shown. The call's own rules run
        # again as the members stand now. A missing member, a guest, a cycle or the depth
        # is the same refusal as the other rules that no longer hold (`409
        # asker_not_allowed`), and the request stays open (§6.2).
        public = values["reports_to"]
        if public is None:
            values["reports_to"] = None
        else:
            try:
                checked = members.validate_assignment(
                    conn,
                    project.id,
                    kind="agent",
                    role=None,
                    reports_to=public,
                    areas=None,
                    capabilities=None,
                    member=target.id,
                    current=(target.trust, target.role),
                )
            except ApiError:
                raise _refuse("the reports_to named in the change does not hold any more") from None
            values["reports_to"] = checked["reports_to"]
    by = principal_id(conn, asker.id)
    assert by is not None
    change = members.Change(project, s.proposer, by, s.approver, None, None)
    dormant = values.pop("dormant", None)
    old: dict[str, Any] = {}
    if values or given:
        old = members.apply_patch(
            conn, change, target, values, (bool(given), reason), instance=proposal.get("instance")
        )
    if dormant is not None:
        # One instance's rest, with the owner's `go` (§6.17); an instance revoked meanwhile
        # leaves nothing to change.
        held = conn.execute(
            select(t.credential).where(
                t.credential.c.membership_id == target.id,
                t.credential.c.instance == proposal.get("instance"),
                t.credential.c.revoked_at.is_(None),
            )
        ).first()
        if held is not None:
            instances.set_dormant(conn, target, held, bool(dormant), by, s.proposer, own=False)
    if asker.agent_id is not None:
        for field in ("trust", "role"):
            if field in old:
                admin_agents.announce(conn, change, target, field, old[field], values[field])


def _proposed(proposal: dict[str, Any], name: str) -> Any:
    if name == "paused":
        return proposal["pause"][1]
    return proposal["values"][name]


def _current(conn: Connection, target: Any, name: str, proposal: dict[str, Any]) -> Any:
    """The member's value at the time of the read."""
    if target is None:
        return None
    instance = proposal.get("instance")
    if name == "paused":
        if instance is None:
            return target.paused_reason if target.paused_since is not None else None
        cred = _credential(conn, target.id, instance)
        return cred.paused_reason if cred is not None and cred.paused_since is not None else None
    if name == "dormant":
        cred = _credential(conn, target.id, instance)
        return bool(cred is not None and cred.dormant_since is not None)
    if name == "availability_policy":
        return availability.policy_of(target)
    if name == "reports_to":
        return principal_id(conn, target.reports_to)
    return getattr(target, name)


def _agent_change(conn: Connection, request: Any, proposal: dict[str, Any]) -> dict[str, Any]:
    """`agent_change` on the request read: every current and proposed value in full, the
    canonical string of the proposed value and the hash stored with the request."""
    target = conn.execute(
        select(t.membership).where(t.membership.c.id == proposal["target"])
    ).first()
    stored_canonical = proposal.get("canonical") or {}
    stored_hash = proposal.get("sha256") or {}
    present = set(stored_canonical)
    if not present:
        present = {key for key in (proposal.get("values") or {}) if key != "role_base"}
        if (proposal.get("pause") or [False])[0]:
            present.add("paused")
    fields = []
    for name in ORDER:
        if name not in present:
            continue
        proposed = _proposed(proposal, name)
        canonical = stored_canonical.get(name)
        digest = stored_hash.get(name)
        if canonical is None or digest is None:
            canonical, digest = _hash(proposed)
        fields.append(
            {
                "name": name,
                "current": _current(conn, target, name, proposal),
                "proposed": proposed,
                "canonical": canonical,
                "sha256": digest,
            }
        )
    return {"agent_change": {"fields": fields}}


def _addressee_only(conn: Connection, request: Any, mine: Any) -> str | None:
    return None


proposals.register(
    KIND,
    settle,
    proposals.Answerer(
        refusal="only the agent's owner answers this consent",
        predicate=_addressee_only,
    ),
    view=_agent_change,
)
