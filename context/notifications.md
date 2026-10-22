# Notifications

## Humans are notified in three stages — dashboard badges, browser notifications, mail over the instance's SMTP — all derived from the events they may read

**Id:** d2d3356f-7a73-4e77-ac7c-3e04b07c2517
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's decision, 2026-10-22, and his answers on the contract pull request the same day (both password sources, the tab total); contract in `docs/api.md` §16.2, §16.3, §17

Humans learn that something waits for them in three stages, all of
them built: badges and a bell in the dashboard (inbox, unread chats,
mentions, changes on their cards; the sum in the tab title), browser
notifications per kind while a dashboard tab is open, and mail through
an SMTP account the operator provides — immediately, as an hourly or
daily digest, or not at all, per kind, with quiet hours and a one-click
unsubscribe per kind. A notification is derived from the events the
human may read, checked again when it is shown and when it is mailed,
so it never reveals more than the human could read in the dashboard.
Mail carries a title and a link back, never a secret, and a private
chat's text only when the human asked for it per kind. The SMTP
password comes from the environment (a Kubernetes Secret) when it is
set there; otherwise the instance admin may set it in the dashboard,
and the hub stores it encrypted with the instance key `MAITY_SECRET_KEY`
and refuses to store it without one. It is write-only either way:
no endpoint returns it. In Kubernetes a password from the database is
flagged with a warning that recommends a Secret. Agents are not part of
it; they keep events and `wait`.

**Reason:** a human who is not looking at the dashboard misses requests
that block agents, and the agents wait. The maintainer wanted every
stage, because each covers what the others miss: the badges when the
tab is in front, the browser when it is in the background, mail when
no tab is open. The tab total counts only what asks for the human —
inbox, chats, mentions — not what merely informs them. The admin-set
password is for a single local install, where an environment variable
or a secret store is more setup than the install itself.

**Rejected alternatives:**
- Mail only: nothing tells a human with the dashboard open, and every
  small change would become a mail.
- In-app only: a human without an open tab learns nothing until they
  look.
- The SMTP password from the environment only, as first proposed:
  safest, but a single local install would need a secret mechanism just
  to send mail. Stored encrypted with an instance key, write-only, and
  flagged in Kubernetes, the admin-set password keeps the plain-text
  risk away without that burden.
