"""The invitation's mail (docs/api.md §3.4, §18.5): the link to an address-bound invitation, sent
when mail is enabled.

It goes through the mail outbox in the caller's transaction, so it leaves only if the invitation
commits, on the invitation budget of its own (§16.2), so invitations never hold up security mail:
over it the mail waits for the next hour, never dropped.
Without mail (not complete or not enabled) nothing is queued and the inviter passes the `url` on,
as the contract says. Plain text, in English, with the inviter's display name and handle, the
project's name, the trust and role, the `note` and the link; the address may belong to nobody on
the hub yet, so the mail names no account of the invitee, and it is tied to an account only where
one holds the address. Tests
replace `send` to see what would go out.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Connection, select

from maity_hub import clock, namespace, registration
from maity_hub import tables as t
from maity_hub.mail import outbox
from maity_hub.plain_text import plain_line


def send(conn: Connection, *, invitation_id: str, to: str, url: str, hub: Any) -> None:
    if not registration.mail_ready(conn, hub):
        return
    invitation = conn.execute(select(t.invitation).where(t.invitation.c.id == invitation_id)).one()
    project = conn.execute(select(t.project).where(t.project.c.id == invitation.project_id)).one()
    inviter = conn.execute(
        select(t.human.c.display_name, t.human.c.handle).where(
            t.human.c.id == invitation.created_by
        )
    ).first()
    subject, body = text(
        inviter=(inviter.display_name if inviter is not None else None) or "Someone",
        inviter_handle=inviter.handle if inviter is not None else None,
        project_name=project.name,
        full_name=namespace.name_of(conn, project.id),
        public_url=hub.public_url,
        trust=invitation.trust,
        role=invitation.role,
        note=invitation.note,
        url=url,
        expires_at=invitation.expires_at,
    )
    # An account that holds this address as verified: the mail is tied to it, so a disabled
    # address stops it as any of that account's mail (§18.7). Most often there is none yet.
    holder = conn.execute(
        select(t.notification_settings.c.human_id).where(
            t.notification_settings.c.address_normalized == registration.normalized(to),
            t.notification_settings.c.address_status.in_(("verified", "disabled")),
        )
    ).scalar()
    outbox.enqueue(conn, kind="invitation", to=to, human_id=holder, subject=subject, body=body)


def text(
    *,
    inviter: str,
    project_name: str,
    full_name: str,
    public_url: str,
    trust: str,
    role: str,
    note: str | None,
    url: str,
    expires_at: Any,
    inviter_handle: str | None = None,
) -> tuple[str, str]:
    """Subject and body of the invitation's mail. What the hub did not write (the inviter's
    name, the project's name, the `note`) is defanged, so that no mail client makes a link of
    it: the only links are the hub's own (§18.5). The subject is one line, whatever the names
    hold, and cut as every subject is; the body names the inviter by display name and handle,
    as the invitation page does (§3.4), each name on one line (§1.7.1). The subject keeps the
    display name alone: the handle would push the project's name toward the cut, and the
    body, which the link is in, names it."""
    from maity_hub.notifications.mailer import defang, quoted, subject_line

    # Folded once, for the subject and the body alike: `subject_line` cleans only Cc, Zl and Zp.
    inviter, project_name = plain_line(inviter), plain_line(project_name)
    title = subject_line(f"[Maity] {inviter} invites you to {project_name}")
    inviter, project_name = defang(inviter), defang(project_name)
    said = f"{inviter} wrote: {quoted(note)}\n\n" if note else ""
    who = f"{inviter} (@{inviter_handle})" if inviter_handle else inviter
    return (
        title,
        f"{who} invites you to the Maity project {project_name} ({full_name}) on "
        f"{public_url}, with trust {trust} and the role {role}.\n\n"
        f"{said}"
        f"Accept the invitation: {url}\n\n"
        f"The link works until {clock.rfc3339(expires_at)} (UTC), once, and only for an "
        "account with this address. If you do not know the sender, ignore this mail.\n",
    )
