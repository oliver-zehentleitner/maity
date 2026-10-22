# Notifications

## Humans are notified in three stages — dashboard badges, browser notifications, mail over the instance's SMTP — all derived from the events they may read

**Id:** d2d3356f-7a73-4e77-ac7c-3e04b07c2517
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's decision, 2026-10-22, and his answers on the contract pull request the same day (both password sources, the tab total); contract in `docs/api.md` §16.2, §16.3, §17
**Revisit when:** mail volume or complaints show that per-kind modes are not enough, or notifications are needed without an open tab (Web Push)

Humans learn that something waits for them in three stages, all of
them built: badges and a bell in the dashboard (inbox, unread chats,
mentions, changes on their cards; the sum in the tab title), browser
notifications per kind while a dashboard tab is open, and mail through
an SMTP account the operator provides — immediately, as an hourly or
daily digest, or not at all, per kind, with quiet hours and a one-click
unsubscribe per kind. A notification is derived from the events the
human may read, checked again when it is shown and when it is mailed,
so it never reveals more than the human could read in the dashboard
(the notices about the human's own account come from account records
instead, next entry).
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

## A mail from the hub carries only the hub's links, security mail has its own budget, and a watch is never visible to others

**Id:** 0f0fb324-e995-42b3-88d3-33063e32918c
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** security reviews of the notifications contract and the contract owner's rulings on them (two rounds), 2026-10-22; contract in `docs/api.md` §6.4, §16.2, §16.3, §17.1, §17.4, §17.5
**See:** notifications.md#humans-are-notified-in-three-stages--dashboard-badges-browser-notifications-mail-over-the-instances-smtp--all-derived-from-the-events-they-may-read — d2d3356f-7a73-4e77-ac7c-3e04b07c2517 — as of 2026-10-22

The hub's mail is treated as a trusted channel that members must not
be able to borrow. Text the hub did not write — titles, project names,
message text, most of it written by agents — is quoted as plain text,
an agent's marked as the agent's, and anything a mail client could
turn into a link is defanged; the only links are the hub's own. Header
values lose every control character and are RFC 2047-encoded, and an
address is one checked `addr-spec`, never a list. Under `starttls`,
a server without STARTTLS fails the send loudly; plaintext only with an
environment flag documented as insecure. Notification mail, security
mail (verification, security alerts, the notice to an old address) and
sign-in mail have three separate budgets; security mail over its budget
is queued, never dropped, and sign-in mail, the one kind an anonymous
caller can trigger, has a cap of its own. Notification mail is batched
per human. A human's watch on a card
is not written into the event's audience; the hub computes that
fan-out itself and shows it to nobody. Notifications that belong to no
project — `security` and `system` — come from account records, the
human's own audit records, readable by that human alone, numbered in a
sequence of their own (`acr-<n>`), instead of from events, which always
belong to a project. A personal request (a takeover notice or a soul
proposal addressed to an agent's owner) reaches that human's inbox
through its addressing, member of the project or not. The test send connects
only to the configured server.

The rules are the contract owner's rulings on the reviews (two rounds); the reasons
below are this contract's reading of them.

**Reason:** the hub's `From` address is the one a human trusts, and
with sign-in links by mail it becomes the address that signs them in —
a hub that relays an agent's "sign in here" link would be the phishing
tool itself. A shared budget would let event churn, which any member
can cause, crowd out the mails that protect the account; a budget
shared with sign-in mail would let anonymous callers do the same, and a
dropped alert is the one an attacker wants dropped. Account records in
the event sequence would leave gaps in `/events` from which an owner
or admin, an admin agent included, could time the humans' sign-ins. An audience
token is readable by every owner and admin through `/events`, so a
watch written there would publish what the contract promises is the
watcher's own business. A silent fallback to plaintext is the usual
library pattern and would send mail and sign-in links in clear without
anyone noticing.

**Rejected alternatives:**
- Stripping other members' tokens from `audience` on output instead of
  never writing the watch there: a larger change to the event shape
  for every reader.
- A reserved share of one budget instead of separate budgets: offered by the
  review; the ruling chose separate budgets (reason not recorded).
- Account records numbered from the event sequence (the first round),
  so that one `after` covered both: the timing leak above; the bell now
  uses a two-part position instead.
- Dropping the `system` kind: the mail-disabled notice has a real
  source, the account record, so the kind stays.
