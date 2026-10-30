"""Deleting your own account (docs/api.md §2.9).

Two steps, so that neither a stolen session nor a read mailbox alone deletes an account:
`POST /me/deletion` with the proof of §2.8.1 and the step-up records a request and mails
a link to the verified address; the link's page asks once more, and its `POST` deletes
the account in one transaction.

The request is a row of `account_deletion` (`live` while it may be confirmed), the link a
signed token (`notifications.tokens`, purpose `account_deletion`) that carries a nonce
whose sha256 is the row's id: the link is bound to that one request and dead once it is
withdrawn, replaced, used or expired. `DELETE /me/deletion`, a newer request, a password
change and a change or removal of the verified address withdraw it (`withdraw`).

The deletion reuses what each removal already does — a membership's removal (§6.2), a
profile's deletion (§6.3), a runner's removal with `agents: stop` (§15.3), an
invitation's voiding (§3.4), a request's withdrawal (§7) — all on the one connection of
the page's `POST`, inside `events.transaction`, so a failure anywhere undoes all of it
and no event is announced. The account row stays with `deleted_at`; its handle stays
taken (the unique column), so it never comes to mean someone else.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import timedelta
from typing import Any

from sqlalchemy import Connection, delete, func, insert, select, update

from maity_hub import clock, github_app, invitations, namespace, orgs, placements, write_guard
from maity_hub import tables as t
from maity_hub.admin import is_instance_admin
from maity_hub.auth import second_factor, sessions
from maity_hub.auth.caller import Caller
from maity_hub.config import Settings
from maity_hub.errors import ApiError, invalid
from maity_hub.events import Actor, lock_project
from maity_hub.mail import address as addresses
from maity_hub.mail import outbox
from maity_hub.mail import settings as mail_settings
from maity_hub.notifications import tokens

PURPOSE = "account_deletion"
VALID_FOR = timedelta(hours=24)
DELETED_NAME = "Deleted account"
# Not a scrypt hash: `passwords.verify_password` answers False for it, whatever is given.
NO_PASSWORD = "deleted"
ENDED_BY = "account_deleted"  # the sessions' `ended_by` (§2.6.5)
HUB = Actor(None)  # the events the deletion writes name no actor: the hub's own change


# --- the request (§2.9 step 1) ------------------------------------------------------------


def view(row: Any) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "requested_at": clock.rfc3339(row.requested_at),
        "expires_at": clock.rfc3339(row.expires_at),
    }


def pending(conn: Connection, human_id: str) -> Any:
    """The human's request that may still be confirmed, or None."""
    row = conn.execute(
        select(t.account_deletion).where(
            t.account_deletion.c.human_id == human_id, t.account_deletion.c.live.is_(True)
        )
    ).first()
    if row is None or clock.now() >= row.expires_at:
        return None
    return row


def withdraw(conn: Connection, human_id: str, by: str) -> bool:
    """Withdraw the human's pending request, if any (`by`: what withdrew it); its link
    is dead from now on. True when there was one, an expired one included."""
    done = conn.execute(
        update(t.account_deletion)
        .where(t.account_deletion.c.human_id == human_id, t.account_deletion.c.live.is_(True))
        .values(live=None, withdrawn_at=clock.now(), withdrawn_by=by)
    ).rowcount
    return bool(done)


def blocker(conn: Connection, human_id: str) -> ApiError | None:
    """Why the account cannot be deleted now: `namespace_owner` while a project in its
    namespace is not archived (§6.25), `last_instance_admin` for the instance's last
    admin (§16); None when nothing stands in the way."""
    open_projects = (
        conn.execute(
            select(t.project.c.id).where(
                t.project.c.owner_id == human_id, t.project.c.state != "archived"
            )
        )
        .scalars()
        .all()
    )
    try:
        namespace.namespace_owner_of(conn, human_id, open_projects)
    except ApiError as refusal:
        return refusal
    alone = orgs.owned_alone(conn, human_id)
    if alone:
        return ApiError(
            409,
            "org_last_owner",
            "the account is the last owner of an organisation",
            {"orgs": alone},
        )
    # The instance has one admin, the earliest account (`admin.instance_admin_id`): that
    # one is always the last.
    if is_instance_admin(conn, human_id):
        return ApiError(
            409,
            "last_instance_admin",
            "the instance's last admin cannot delete the account",
        )
    return None


def lock_account(conn: Connection, human_id: str) -> None:
    """Take the human's `account_lock` exclusively: the first lock of a deletion."""
    write_guard.ensure_row(conn, human_id)
    conn.execute(
        select(t.account_lock.c.human_id)
        .where(t.account_lock.c.human_id == human_id)
        .with_for_update()
    ).first()


def _lock_namespace(conn: Connection, human_id: str) -> None:
    """`lock_project` on every project in the human's namespace, in a stable order."""
    for project_id in (
        conn.execute(
            select(t.project.c.id).where(t.project.c.owner_id == human_id).order_by(t.project.c.id)
        )
        .scalars()
        .all()
    ):
        lock_project(conn, project_id)


def _verified_address(conn: Connection, human_id: str) -> str | None:
    row = conn.execute(
        select(t.notification_settings.c.address, t.notification_settings.c.address_status).where(
            t.notification_settings.c.human_id == human_id
        )
    ).first()
    if row is None or row.address is None or row.address_status != "verified":
        return None  # a disabled address receives nothing (§18.7): no way to confirm
    return str(row.address)


def request(conn: Connection, hub: Settings, caller: Caller, confirm: str) -> dict[str, Any]:
    """`POST /me/deletion`: the proof (§2.8.1), the step-up (§2.8.4), the caller's own
    handle as `confirm`, then the refusals; records the request, replacing an older one,
    and mails the confirmation link. Returns the `deletion` view."""
    second_factor.require_proof(conn, caller)
    second_factor.require_step_up(conn, hub, caller)
    # The human's row orders this with a concurrent request, password change or deletion.
    human = conn.execute(
        select(t.human).where(t.human.c.id == caller.principal_id).with_for_update()
    ).one()
    if confirm != human.handle:
        raise invalid({"confirm": "mismatch"}, "confirm with your own handle")
    refusal = blocker(conn, human.id)
    if refusal is not None:
        raise refusal
    if not mail_settings.resolve(conn, hub.mail, hub.secret_key).complete:
        raise ApiError(409, "mail_not_configured", "the instance cannot send mail")
    address = _verified_address(conn, human.id)
    if address is None:
        raise ApiError(409, "address_unverified", "the account has no verified address")
    withdraw(conn, human.id, "replaced")
    now = clock.now()
    nonce = secrets.token_urlsafe(24)
    conn.execute(
        insert(t.account_deletion).values(
            id=_digest(nonce),
            human_id=human.id,
            requested_at=now,
            expires_at=now + VALID_FOR,
            live=True,
        )
    )
    key = hub.mail.signing_key
    assert key is not None  # a complete mail setting includes the signing key
    token = tokens.make(
        key, {"h": human.id, "p": PURPOSE, "n": nonce, "x": int((now + VALID_FOR).timestamp())}
    )
    _mail(conn, hub.public_url, human, address, token)
    return {"requested_at": clock.rfc3339(now), "expires_at": clock.rfc3339(now + VALID_FOR)}


def _digest(nonce: str) -> str:
    return hashlib.sha256(nonce.encode()).hexdigest()


def export_url(public_url: str) -> str:
    """The dashboard's account page, which signs in and asks for the step-up before the
    export: never the API route (§2.9)."""
    return f"{public_url}/account"


def _mail(conn: Connection, public_url: str, human: Any, address: str, token: str) -> None:
    """The security mail of §2.9: what deletion does, the link to confirm and the link to
    the export. Sent whatever the security mode says, as the address's own confirmation
    is (§18.4); it counts against the security budget (§16.2)."""
    outbox.enqueue(
        conn,
        kind="security",
        human_id=human.id,
        to=address,
        extra_headers={"_purpose": PURPOSE},
        subject="[Maity] Confirm the deletion of your account",
        body=(
            f"Someone signed in to your Maity account at {public_url} and asked to delete "
            f"it on {clock.rfc3339(clock.now())}.\n\n"
            "Deleting it ends every session, removes your address, name, picture and "
            "settings, ends your memberships, deletes your agent profiles and removes your "
            "runners. What you wrote stays in its projects as written by a deleted "
            "account; redact it first if you want it gone.\n\n"
            f"Take your data with you first: {export_url(public_url)}\n\n"
            f"Confirm the deletion: {public_url}/mail/account-deletion/{token}\n\n"
            "The link is valid for 24 hours and works once. Nothing changes until you "
            "confirm. If this was not you, change your password: that withdraws the "
            f"request. Your sessions: {public_url}/account/sessions\n"
        ),
    )


# --- the link (§2.9 step 2, §18.6) ----------------------------------------------------------


def _alive(conn: Connection, signing_key: bytes | None, token: str, *, lock: bool) -> Any:
    """The pending request the token names, or None for every link that does not work:
    not ours, another purpose, withdrawn, replaced, used or expired — never which."""
    payload = tokens.read(signing_key, token)
    if payload is None or payload.get("p") != PURPOSE or not isinstance(payload.get("n"), str):
        return None
    query = select(t.account_deletion).where(
        t.account_deletion.c.id == _digest(payload["n"]),
        t.account_deletion.c.human_id == str(payload.get("h")),
        t.account_deletion.c.live.is_(True),
    )
    row = conn.execute(query.with_for_update() if lock else query).first()
    if row is None or row.used_at is not None or clock.now() >= row.expires_at:
        return None
    return row


def page(conn: Connection, signing_key: bytes | None, token: str) -> Any:
    """What the link's `GET` shows: the human whose request it is, or None. Writes nothing."""
    row = _alive(conn, signing_key, token, lock=False)
    if row is None:
        return None
    human = conn.execute(select(t.human).where(t.human.c.id == row.human_id)).one()
    return None if human.deleted_at is not None else human


def confirm(conn: Connection, hub: Settings, token: str) -> str | None:
    """The link's `POST`: delete the account the token names. Returns `deleted`, the
    refusal's code (`namespace_owner`, `last_instance_admin`: nothing is deleted and the
    link keeps working), or None for a link that does not work. Must run inside
    `events.transaction`: the removals it reuses defer work to the commit."""
    payload = tokens.read(hub.mail.signing_key, token)
    if payload is None or payload.get("p") != PURPOSE:
        return None
    human_id = str(payload.get("h"))
    # The account's lock before any other (`write_guard`): every transaction of the
    # human's own calls (a newer request, a password or address change) and an address's
    # confirmation link hold it shared before their first lock, so each either commits
    # before this one (and this link may be dead) or waits for it. The human row needs
    # no lock of its own here: ordinary work locks it after project locks, and taking
    # it before the projects would invert that order.
    lock_account(conn, human_id)
    human = conn.execute(select(t.human).where(t.human.c.id == human_id)).first()
    if human is None or human.deleted_at is not None:
        return None
    row = _alive(conn, hub.mail.signing_key, token, lock=True)
    if row is None:
        return None
    # The organisations before any project, in the order of their ids (§6.26): a promotion or
    # a transfer into an organisation takes the same order.
    orgs.lock_all_of(conn, human.id)
    # The namespace's projects under their locks before the re-check: a state change
    # takes the same lock, so a reopen commits first (and this refuses) or waits.
    _lock_namespace(conn, human.id)
    refusal = blocker(conn, human.id)
    if refusal is not None:
        return refusal.code
    used = conn.execute(
        update(t.account_deletion)
        .where(t.account_deletion.c.id == row.id, t.account_deletion.c.live.is_(True))
        .values(live=None, used_at=clock.now())
    ).rowcount
    if used != 1:
        return None  # another POST of the same link won
    delete_account(conn, hub, human.id)
    return "deleted"


# --- what deletion does (§2.9) ------------------------------------------------------------------


def delete_account(conn: Connection, hub: Settings, human_id: str) -> None:
    """Delete the account in the caller's transaction, in the order §2.9 lists, each part
    through the code that already does it elsewhere."""
    from maity_hub.routes import runners as runner_routes
    from maity_hub.routes.agents import delete_profile

    now = clock.now()
    # Its runners, as `DELETE /runners/{id}` with `agents: stop` (§15.3): placements
    # closed, the agents' credentials revoked at once, the runner credential revoked.
    for runner_id in _ids(
        conn,
        select(t.runner.c.id)
        .where(t.runner.c.owner_id == human_id, t.runner.c.removed_at.is_(None))
        .order_by(t.runner.c.id)
        .with_for_update(),
    ):
        runner_routes.remove(
            conn, runner_id, agents="stop", instance_rule=hub.on_runner_revoke, by=human_id
        )
    # Its unused runner enrollments (§15.2) and agent joins (§3.1).
    conn.execute(
        update(t.runner_enrollment)
        .where(
            t.runner_enrollment.c.created_by == human_id,
            t.runner_enrollment.c.used_at.is_(None),
            t.runner_enrollment.c.burned_at.is_(None),
            t.runner_enrollment.c.revoked_at.is_(None),
        )
        .values(revoked_at=now)
    )
    conn.execute(
        update(t.join_link)
        .where(
            t.join_link.c.created_by == human_id,
            t.join_link.c.placement_id.is_(None),  # a runner's pickup (§15.9) is not one
            t.join_link.c.used_at.is_(None),
            t.join_link.c.burned_at.is_(None),
            t.join_link.c.revoked_at.is_(None),
        )
        .values(revoked_at=now)
    )
    # Placements it created whose membership is not made yet (§15.6): closed at once,
    # as the runner never ran an agent for them; an open consent request withdrawn.
    for placement in placements.active_rows(
        conn, t.placement.c.created_by == human_id, t.placement.c.membership_id.is_(None)
    ):
        lock_project(conn, placement.project_id)
        placements.withdraw_open_request(conn, placement, "the account was deleted", None)
        placements.close_now(conn, placements.row(conn, placement.id), "removed", None, human_id)
    # Invitations it issued that are still open (§3.4).
    for invitation in conn.execute(
        select(t.invitation)
        .where(t.invitation.c.created_by == human_id)
        .order_by(t.invitation.c.created_at, t.invitation.c.id)
    ).all():
        if invitations.state(invitation, now) == "open":
            lock_project(conn, invitation.project_id)
            invitations.void(conn, invitation, HUB)
    # A held decision goes back to the admins while its membership still names it.
    _return_held(conn, human_id)
    # Its agent profiles, as §6.3 deletes one with `cascade` (§19.1).
    owned = _ids(
        conn,
        select(t.agent_profile.c.id)
        .where(t.agent_profile.c.owner_id == human_id)
        .order_by(t.agent_profile.c.id)
        .with_for_update(),
    )
    for agent_id in _ids(
        conn,
        select(t.agent_profile.c.id).where(
            t.agent_profile.c.id.in_(owned), t.agent_profile.c.deleted_at.is_(None)
        ),
    ):
        delete_profile(
            conn, agent_id, actor_in=lambda _project_id: HUB, by=human_id, credential_id=None,
            via=None,
        )  # fmt: skip
    # Every profile's git identity and soul with its versions go, the tombstones of
    # profiles deleted before included: §6.3 keeps those, the account's deletion not.
    if owned:
        conn.execute(
            update(t.agent_profile)
            .where(t.agent_profile.c.id.in_(owned))
            .values(git_name=None, git_email=None)
        )
        conn.execute(delete(t.soul_version).where(t.soul_version.c.agent_id.in_(owned)))
        conn.execute(delete(t.soul).where(t.soul.c.agent_id.in_(owned)))
    # Its memberships in organisations end (§2.9, §6.26); the check that it is nobody's last
    # owner is `blocker`, made under the organisations' locks. Before the project memberships
    # end: the `member_updated` of a seat the hub kept must not say `org_owner`.
    from maity_hub import org_invitations, project_names

    org_invitations.withdraw_by_inviter_everywhere(conn, human_id, "inviter_deleted")
    project_names.withdraw_started_by(conn, human_id, "initiator_deleted")
    conn.execute(delete(t.org_member).where(t.org_member.c.human_id == human_id))
    _leave_projects(conn, human_id)
    _forget_confirmations(conn, human_id)
    # The personal requests last, once removing the profiles cannot file another.
    _withdraw_personal(conn, human_id)
    _end_access(conn, hub, human_id)
    _remove_person(conn, human_id, hub.secret_key)


def _ids(conn: Connection, query: Any) -> list[str]:
    return [str(found) for found in conn.execute(query).scalars().all()]


def _withdraw_personal(conn: Connection, human_id: str) -> None:
    """Its open personal requests are withdrawn (§7). Open cross-owner `reports_to`
    consents (§6.2) do not exist in this hub yet: nothing files them, so there is
    nothing to withdraw."""
    from maity_hub import org_invitations
    from maity_hub.routes.requests import close_request

    # An organisation's invitations to the human first: they have no project to lock (§6.26).
    org_invitations.withdraw_for_human(conn, human_id, "invitee_deleted")
    for request_id in _ids(
        conn,
        select(t.request.c.id)
        .where(
            t.request.c.personal.is_(True),
            t.request.c.to_human == human_id,
            t.request.c.status == "open",
        )
        .order_by(t.request.c.created_at, t.request.c.id),
    ):
        project_id = conn.execute(
            select(t.request.c.project_id).where(t.request.c.id == request_id)
        ).scalar_one()
        if project_id is not None:
            lock_project(conn, project_id)
        close_request(conn, request_id, "withdrawn", None, reason="the account was deleted")


def _return_held(conn: Connection, human_id: str) -> None:
    """A `decision` request one of its memberships, or one of its agents', holds after a
    forward or a claim goes back to the admins (`holder: trust:admin`, §7)."""
    from maity_hub.routes.requests import return_to_pool

    agents = select(t.agent_profile.c.id).where(t.agent_profile.c.owner_id == human_id)
    mine = select(t.membership.c.id).where(
        (t.membership.c.human_id == human_id) | t.membership.c.agent_id.in_(agents)
    )
    for request_id in _ids(
        conn,
        select(t.request.c.id)
        .where(t.request.c.holder_member.in_(mine), t.request.c.status == "open")
        .order_by(t.request.c.created_at, t.request.c.id),
    ):
        return_to_pool(conn, request_id, human_id, "the holder's account was deleted")


def _leave_projects(conn: Connection, human_id: str) -> None:
    """Every membership ends as a removal does (§6.2), with the hub as actor. The
    namespace check of a removal does not apply: an open project of the namespace
    refused the deletion already, and in an archived one the last owner may go."""
    from maity_hub.routes.members import Change, apply_remove

    for membership_id in (
        conn.execute(
            select(t.membership.c.id)
            .where(t.membership.c.human_id == human_id, t.membership.c.active.is_(True))
            .order_by(t.membership.c.id)
        )
        .scalars()
        .all()
    ):
        target = conn.execute(select(t.membership).where(t.membership.c.id == membership_id)).one()
        project = lock_project(conn, target.project_id)
        apply_remove(conn, Change(project, HUB, human_id, human_id, None, None), target)


def _forget_confirmations(conn: Connection, human_id: str) -> None:
    """The repositories it confirmed are not confirmed any more: their grants end with the
    account (§11.4); another owner of the organisation confirms again."""
    for project_id in _ids(
        conn,
        select(t.project.c.id)
        .where(t.project.c.repository_confirmed_by == human_id)
        .order_by(t.project.c.id),
    ):
        lock_project(conn, project_id)
        conn.execute(
            update(t.project)
            .where(t.project.c.id == project_id)
            .values(repository_owner_confirmed=False, repository_confirmed_by=None)
        )


def _end_access(conn: Connection, hub: Settings, human_id: str) -> None:
    """Every session and device code ends; the second factor, its recovery codes, reset
    links and the device cookies' values go; the forge links with their state and token
    and the pending sign-in links go, with the day's count of wrong codes (§2.9, §11.4,
    §2.6.3); the pending mail to the account is dropped (§18.7)."""
    sessions.end_where(conn, t.human_session.c.human_id == human_id, ENDED_BY)
    installations = list(
        conn.execute(
            select(t.forge_link.c.installation_id).where(t.forge_link.c.human_id == human_id)
        ).scalars()
    )
    conn.execute(delete(t.forge_link_state).where(t.forge_link_state.c.human_id == human_id))
    conn.execute(delete(t.forge_token).where(t.forge_token.c.human_id == human_id))
    conn.execute(delete(t.forge_link).where(t.forge_link.c.human_id == human_id))
    if hub.github_app is not None:  # an installation's cached token, as an unlink drops it
        for installation_id in installations:
            github_app.forget_token(hub.github_app, installation_id)
    conn.execute(delete(t.email_sign_in).where(t.email_sign_in.c.human_id == human_id))
    conn.execute(delete(t.email_sign_in_day).where(t.email_sign_in_day.c.human_id == human_id))
    conn.execute(
        update(t.device_code)
        .where(
            t.device_code.c.human_id == human_id,
            t.device_code.c.status.in_(("waiting", "redeemed", "approved")),
        )
        .values(status="denied")
    )
    conn.execute(delete(t.recovery_code).where(t.recovery_code.c.human_id == human_id))
    conn.execute(delete(t.second_factor_reset).where(t.second_factor_reset.c.human_id == human_id))
    conn.execute(delete(t.second_factor).where(t.second_factor.c.human_id == human_id))
    conn.execute(delete(t.human_device).where(t.human_device.c.human_id == human_id))
    # What the sessions and device codes said about the browser goes with them; the
    # addresses went when each ended (`sessions.end_where`).
    conn.execute(
        update(t.human_session)
        .where(t.human_session.c.human_id == human_id)
        .values(browser=None, os=None, ip=None, source=None, next=None)
    )
    conn.execute(
        update(t.device_code)
        .where(t.device_code.c.human_id == human_id)
        .values(ip=None, user_agent=None, browser=None, os=None, next=None)
    )
    # Pending mail to the account is dropped (§18.7).
    conn.execute(
        update(t.mail_outbox)
        .where(
            t.mail_outbox.c.human_id == human_id,
            t.mail_outbox.c.status.in_(("waiting", "sending")),
        )
        .values(status="dropped")
    )


def _remove_person(conn: Connection, human_id: str, secret_key: bytes | None) -> None:
    """The address, picture, languages, preferences and notification settings go, with
    the account's own records and its declared limit; the row stays with `deleted_at`,
    its handle taken for good (§2.9). The row is written last: ordinary work locks it
    after project locks (account records), and so does the deletion; what the removals
    wrote into events before it is shaped when read (`views.shape_deleted`). The hub has no
    public profile or static pages of a human yet (§16.9), and no handle aliases
    (§6.24)."""
    known = _addresses(conn, human_id)
    _forget_mail(conn, human_id, known)  # its pending registrations go here too
    addresses.forget_locks(conn, secret_key, known)
    for table in (
        t.notification_settings,  # the address, the language, the mail settings
        t.preferences_version,
        t.preferences,
        t.mail_item_sent,
        t.notification_mail_state,
        t.notification_read,
        t.notification_position,
        t.account_record,  # sign-ins with their addresses and browsers, address changes
    ):
        conn.execute(delete(table).where(table.c.human_id == human_id))
    conn.execute(delete(t.avatar_image).where(t.avatar_image.c.owner_id == human_id))
    conn.execute(
        update(t.account_registration)
        .where(t.account_registration.c.human_id == human_id)
        .values(address=None, address_normalized=None, source_ip=None)
    )
    conn.execute(
        update(t.human)
        .where(t.human.c.id == human_id)
        .values(
            display_name=DELETED_NAME,
            password_hash=NO_PASSWORD,
            limit_until=None,
            limit_since=None,
            limit_reason=None,
            limit_show_reason_in=None,
            deleted_at=clock.now(),
        )
    )


def _addresses(conn: Connection, human_id: str) -> set[str]:
    """Every address the hub holds for the account, normalized: the verified one, one
    waiting for its link, a held change, the registration's."""
    found: set[str] = set()
    settings = conn.execute(
        select(t.notification_settings).where(t.notification_settings.c.human_id == human_id)
    ).first()
    if settings is not None:
        held = (settings.address_change or {}).get("address")
        found.update(a for a in (settings.address, settings.pending_address, held) if a)
    registered = conn.execute(
        select(t.account_registration.c.address).where(
            t.account_registration.c.human_id == human_id
        )
    ).scalar()
    if registered:
        found.add(registered)
    return {addresses.normalized(a) for a in found}


def _forget_mail(conn: Connection, human_id: str, known: set[str]) -> None:
    """No mail row keeps the person (§2.9): every outbox row of the account, and every
    row sent to one of its addresses (an invitation, a registration's link), loses its
    recipient, subject, text and headers, whatever its status; kind, status, times and
    attempts stay for the counters. `mail_delivery` holds no address. Pending
    registrations of those addresses go, and so does the address on an invitation the
    account used: it was bound to this person."""
    mine = t.mail_outbox.c.human_id == human_id
    if known:
        mine = mine | func.lower(func.trim(t.mail_outbox.c.recipient)).in_(known)
    conn.execute(
        update(t.mail_outbox).where(mine).values(recipient="", subject="", body="", headers={})
    )
    if known:
        conn.execute(
            delete(t.pending_registration).where(
                t.pending_registration.c.address_normalized.in_(known)
            )
        )
    conn.execute(
        update(t.invitation)
        .where(t.invitation.c.used_by == human_id, t.invitation.c.address.is_not(None))
        .values(address=None, address_normalized=None)
    )
