"""The invitation's mail (docs/api.md §3.4, §18.5): the link to an address-bound
invitation, sent when mail is enabled.

The mail outbox comes with the notification settings (#280); until then this sends
nothing and the inviter passes the `url` on, as the contract says for a hub without
mail. Tests replace `send` to see what would go out.
"""

from __future__ import annotations

from sqlalchemy import Connection


def send(conn: Connection, *, invitation_id: str, to: str, url: str) -> None:
    # TODO(#280): enqueue the §18.5 mail (inviter, project, role, note, link) in the
    # outbox, under the recipient's security-mail budget.
    del conn, invitation_id, to, url
