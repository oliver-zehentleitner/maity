# Notifications

## Humans are notified in three stages — dashboard badges, browser notifications, mail over the instance's SMTP — all derived from the events they may read

**Id:** d2d3356f-7a73-4e77-ac7c-3e04b07c2517
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's decision, 2026-10-22, and his answers on the contract pull request the same day (both password sources, the tab total); contract in `docs/api.md` §16.2, §16.3, §18
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
**Source:** security reviews of the notifications contract and the contract owner's rulings on them (four rounds), 2026-10-22 and 2026-10-23; contract in `docs/api.md` §6.4, §16.2, §16.3, §18.1, §18.4, §18.5
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
proposal addressed to an agent's owner) is an account record of that
human too — one record per state change — so it reaches their inbox
once, member of the project or not. Because the bell reads two
sequences, its position is two-part, read from one snapshot and only
ever moved forward per component; its numbers and times come from the
database, since several hub replicas write at once. Security items are
read only one by one — never by age and never by "mark all read",
which would confirm an intruding session in passing. The test send connects
only to the configured server.

The rules are the contract owner's rulings on the reviews (four rounds); the reasons
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
- Personal requests as a third source beside events and records (the
  second round): it had no id, position or read flag of its own and
  counted differently for members and non-members.
- Dropping the `system` kind: the mail-disabled notice has a real
  source, the account record, so the kind stays.

## The bell's position is an opaque token of per-project positions, ordered per project and per account, never globally

**Id:** b735056d-fb73-458b-8a85-d656dc7e218b
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** decision by the contract owner, 2026-10-23, and the owner's rulings on the review of that change, 2026-10-23; contract in `docs/api.md` §1.4, §1.7, §18.2, §18.3, §18.8
**See:** notifications.md#a-mail-from-the-hub-carries-only-the-hubs-links-security-mail-has-its-own-budget-and-a-watch-is-never-visible-to-others — 0f0fb324-e995-42b3-88d3-33063e32918c — as of 2026-10-23
**Revisit when:** the hub gains a hub-wide write order that every supported database provides, or the per-project lock (`lock_project`) changes

The position the bell resumes from (`after`, `next_after`, `up_to`)
is an opaque token that clients pass back unchanged. It holds one
position per project the human is a member of (that project's highest
`seq` covered) and one for the human's account records. Visibility
order is guaranteed per project, by the project lock held until commit
while a `seq` is allocated, and per account, by a lock on the account
row; `at` is monotonic along the same lines, not globally. A project
joined later starts at its position at join time, a project left drops
out. The token is sealed with AES-256-GCM under a position key,
bound to the human's account id and the purpose
`notifications.position`, and names projects by id. The position key
is derived from `MAITY_SECRET_KEY` (HKDF) when that is set, and
otherwise is a random key the hub creates at first use and keeps in
its own database, so positions never depend on the instance key being
set; changing that setting invalidates every position; the normal form is
the sealed vector inline, and when that would exceed the length cap
the hub stores the vector (immutable, kept at least 30 days after last
use) and hands out a sealed handle instead. A position that does not
open for the human (forged, altered, another human's, expired, the
earlier two-part form) is `invalid` with one answer for every case,
never read as the head. Recovery is split: an invalid `after` lets the
client restart at the head, giving up the browser notifications of the
items in between; an invalid `up_to` marks nothing and is not retried
on its own. This replaces the two-part position `a.b` and its
promise that numbers become visible in global order, recorded in the
entry above.

**Reason:** a global visibility order needs a hub-wide write mutex.
Transactions that emit in several projects exist (runner revoke and
remove, leak revocation, avatar change, `soul_changed`, profile
delete), so a global lock taken next to the project locks deadlocks
against ordinary writes. Per-project positions need only the locks
the hub already takes. A plain encoded token cannot tell another
human's token apart and shows the projects it names to whoever holds
it; sealing it, bound to the human's id, does both. The seal guards
against a client forging, altering or reusing another human's token;
whoever can read the database can read every notification anyway, so
a key held in that database is adequate where no instance key is set,
and the bell keeps working on an install without one.
Reading a bad position as the head would silently skip items, and an
automatic retry of "mark all read" with a fresh position would mark
items the human never saw, so only the long-poll restarts on its own.
Dropping components or resetting to the head to stay under the length
cap would skip items too, hence the stored overflow form.

**Rejected alternatives:**
- A global sequence lock held until commit: deadlocks on multi-project
  writes, and serialises all writes hub-wide.
- Gap tracking with a time horizon: correctness rests on every
  transaction finishing within the horizon.
- A database-specific safe-snapshot sequence (`pg_snapshot_xmin`): no
  MariaDB or SQLite equivalent.
- The position as plain base64url JSON with project slugs (the first
  draft of this change): no binding to the human and readable by
  anyone who holds it.
- Sealing only under `MAITY_SECRET_KEY` itself: the key is optional,
  and the bell would not work on an instance without it.

## "Waiting for you" gathers everything that waits for the human, not only the inbox

**Id:** b59cf365-78a6-4a31-be85-b586d8e19695
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's request, 2026-10-23, looking at the all-projects start page; contract in `docs/api.md` §18.8

The all-projects start page used to list open requests only, so a
human had to visit chats, threads and boards separately to see what
else waited. It now shows everything in one place: open requests
first, because they need an answer, then the unread items of the
notifications feed grouped for reading — one row per conversation or
thread, then mentions, the human's cards, agent outages and ticker
items. It reuses the feed the bell already reads, so it costs no new
endpoint and never shows more than the human may read.

Rejected: a separate aggregation endpoint for the page (a second source
of truth next to the notifications feed); keeping the inbox-only page
and pointing to the bell (the start page is where the human looks
first). The per-kind switches of §18.4 govern browser notifications and
mail, not this page, so nothing waiting is hidden from it.

## A notification is something the human must react to, not an activity log

**Id:** 1ebd4cc1-6f1b-445f-8c88-98103a4bc3ef
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** maintainer decision 2026-10-26 in chat; contract in `docs/api.md` §6.23, §15.7, §16.4, §17.10, §18, §20.9
**See:** notifications.md#humans-are-notified-in-three-stages--dashboard-badges-browser-notifications-mail-over-the-instances-smtp--all-derived-from-the-events-they-may-read — d2d3356f-7a73-4e77-ac7c-3e04b07c2517 — as of 2026-10-26
**See:** notifications.md#waiting-for-you-gathers-everything-that-waits-for-the-human-not-only-the-inbox — b59cf365-78a6-4a31-be85-b586d8e19695 — as of 2026-10-26

A notification is what the human has to react to: someone trying to
reach them (`chat`, `mention`) or something in their inbox (`inbox`),
plus the `security` alerts, which stay outside `total`. The kinds
`card`, `ticker`, `jour_fixe`, `keep_the_why`, `agent`, `system` and
`registration` are gone; the events behind them are unchanged and the
board, the ticker and the project's feed show them. What needed an
answer moves into the inbox: an agent's outage and an unconfirmed Keep
the Why commitment become personal requests of class `info` to the
agent's owner, filed once per outage or commitment and withdrawn by the
hub on recovery or confirmation; a pending registration and a disabled
mail address are `inbox` items counted until decided or fixed; a jour
fixe reaches humans through the requests its report files and through
the round itself; an approved registration notifies nobody. The derive
reads only chat and mention messages, request events and account
records instead of every event kind of its window. This narrows the
first entry's badges ("changes on their cards") and the groups of
"Waiting for you" (cards, agent outages, ticker items), and drops the
`system` kind that the second entry kept.

**Reason:** a notification is something the human must react to; a
thousand entries a day do not help. The volume of the activity kinds
buried the few items that ask for the human, and it made the derive
scan every event of every project.

**Rejected alternatives:**
- Keep the activity-log kinds and only optimise the derive: the volume
  itself is the problem for the human, not the cost of computing it.
- Drop `security` too: security alerts protect the account, so they
  stay, outside `total` as before.
- Tell the placement's creator about an outage too, when that human is
  not the agent's owner: the owner is responsible for the agent, and
  one addressee keeps one request per outage.
- Keep card watches as a notification source: that is the activity log
  again; the watch stays as a board feature.
