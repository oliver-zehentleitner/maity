"""The invitation's mail (docs/api.md §3.4, §18.5): the link to an address-bound invitation, sent
when mail is enabled.

It goes through the mail outbox in the caller's transaction, so it leaves only if the invitation
commits, on the security budget (§16.2): over it the mail waits for the next hour, never dropped.
Without mail (not complete or not enabled) nothing is queued and the inviter passes the `url` on,
as the contract says. Plain text, in English, with the inviter's display name, the project's name,
the trust and role, the `note` and the link; the address may belong to nobody on the hub yet, so
the mail names no account. Tests replace `send` to see what would go out.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Connection, select

from maity_hub import clock, namespace, registration
from maity_hub import tables as t
from maity_hub.mail import outbox


def send(conn: Connection, *, invitation_id: str, to: str, url: str, hub: Any) -> None:
    if not registration.mail_ready(conn, hub):
        return
    invitation = conn.execute(select(t.invitation).where(t.invitation.c.id == invitation_id)).one()
    project = conn.execute(select(t.project).where(t.project.c.id == invitation.project_id)).one()
    inviter = conn.execute(
        select(t.human.c.display_name).where(t.human.c.id == invitation.created_by)
    ).scalar()
    subject, body = text(
        inviter=inviter or "Someone",
        project_name=project.name,
        full_name=namespace.name_of(conn, project.id),
        public_url=hub.public_url,
        trust=invitation.trust,
        role=invitation.role,
        note=invitation.note,
        url=url,
        expires_at=invitation.expires_at,
    )
    outbox.enqueue(conn, kind="security", to=to, subject=subject, body=body)


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
) -> tuple[str, str]:
    """Subject and body of the invitation's mail. The `note` is the inviter's own words, plain
    text, never made into a link (§18.5)."""
    said = f"{inviter} wrote:\n\n{note}\n\n" if note else ""
    return (
        f"[Maity] {inviter} invites you to {project_name}",
        f"{inviter} invites you to the Maity project {project_name} ({full_name}) on "
        f"{public_url}, with trust {trust} and the role {role}.\n\n"
        f"{said}"
        f"Accept the invitation: {url}\n\n"
        f"The link works until {clock.rfc3339(expires_at)} (UTC), once, and only for an "
        "account with this address. If you do not know the sender, ignore this mail.\n",
    )
