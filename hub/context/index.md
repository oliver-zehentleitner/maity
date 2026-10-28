# Context index

Why the hub (`hub/`, the server) is built the way it is. Family-wide decisions are in the root [`context/`](../../context/index.md).

## 0

## 1

## 2

## 3

## 4

## 5

## 6

## 7

## 8

## 9

## A
- [attachments.md](attachments.md) — without MAITY_ATTACHMENT_DIR the hub starts with attachments off and every attachment call says `attachments_not_configured` (the coordinator's ruling, #464); the blob is written before the row and removed when the row never commits; a pending upload is its uploader's alone and the rate counts 64 KiB units; a message names its attachments in its own transaction and always carries the list; redaction tombstones them with the message; the project view's quota is filled where the caller is known; the sweep keeps rows and bytes equal and trusts no young blob; an owner outside the project reads a group chat's files through a gated stand-in row; deleting a sent file follows who the message is for
- [auth.md](auth.md) — a call's presence and lease side effects commit before the endpoint runs; a runner caller is confined before any route runs; an admin agent's members:admin as two endpoints, not the scope; a session's public id, named browser and system, no address kept once it ends; good standing by password only and `not_implemented` for the mail link until the other methods exist; device-code long-polls read the row, the device cookie holds one value per human; a pending account confined in the same place; no registration before the operator's account exists; two-factor: enrolment derived per call, the second step re-keys the session, wrong codes counted in the process
- [availability.md](availability.md) — availability computed on read, the announced state stored and reconciled under the project lock by requests and a one-minute sweep; an agent's first look a silent baseline; a limit only lengthens leases; a human's limit on the account

## B
- [board.md](board.md) — batched forge reads; event-linked and authored-only mirror history; final-state subtask approval and graph checks; computed child counts; completion-error compatibility

## C

## D

## E
- [events.md](events.md) — the long-poll waits on an asyncio event in-process, never on the database; a runner's stream reads every project it was ever attached to; mention pings counted in process, given back when the write does not commit; shared environments computed from live sessions, only announcements stored; the project message listing runs the events through the same read rule in Python, with a cursor bound to its query

## F

## G

## H

## I
- [images.md](images.md) — a project's logo and banner: the forge's images as rows next to the uploads, refreshed by a worker that needs no token; image routes choose their own caching; a 1 MiB cap for uploads only; avatars decoded in a self-limiting process (-I, empty environment, size from the header first); replays first, the change limit counts refused images; a GitHub logo is the owner's avatar only for an organization; an attachment's image runs through the same child in an attachment mode (8192 px, 40 MP, kept size, sRGB, PNG/JPEG/WebP out)
- [instances.md](instances.md) — an agent's claim always names its instance, none held by nobody; the rulebook through the member PATCH with team alone, a non-member owner included; a replacement moves claims and lead before revoking; what a rollback and old join links do; the team wake stored per team at write; PATCH /me pauses the calling instance; instance_assigned only for the team's own cards (open); an instance mention resolves to any live instance, a malformed suffix is a boundary; a chat message's and a request's instance read from the credential behind them, not stored

## J
- [joins.md](joins.md) — the join page's HTML via markdown-it-py with raw HTML off; the template shipped from docs/ into the wheel; the join host as a path rewrite in the middleware, matched on the hostname alone (fails closed); unused join links and new-profile placements lose reports_to with the removed member, the exchange keeps only an active boss; invitations voided at accept, listed 30 days from their own end, the page's registration from the effective mode and mail
- [jour-fixe.md](jour-fixe.md) — minutes online for the moderator order counted per agent membership and minute in their own table; a round's thread opens with the round, a pending further step waits in the steps list; the thread and its messages wake nobody; a proposal's decision request asked by the moderator; a later adopt opens the card, the report stays final; a card still carries the hub's text while it is exactly what the hub wrote

## K
- [keep-the-why.md](keep-the-why.md) — the Keep the Why export in memory: read through on request, refreshed in the background for the project view, never stored
- [kubernetes.md](kubernetes.md) — one pod with Recreate, no replica count; migrations as a pre-install/pre-upgrade hook Job; readiness on health, liveness on help; a plain Ingress with ingress-nginx defaults (retired upstream); serving only on its own schema head, no rollback downgrade

## L

## M
- [mail.md](mail.md) — mail counters from a delivery table, the SMTP conversation on smtplib stage by stage, `tls: none` checked on the resolved pair; the test send counts against no budget, needs `to` until addresses exist, keeps `last_test` unless a connection value really changes; mail through an outbox written in the deciding transaction and sent by a worker, a row claimed by one conditional update that lapses after two minutes
- [memory.md](memory.md) — memory caps count UTF-8 bytes under the project lock; `q` filters in Python; an agent's community entry is a proposal through the shared mechanism, only a `project:admin` human answers it, soul proposals use the same registry through the profile owner’s personal inbox; `changed_since_cursor` reads the memory events after the cursor; another team's agent gets `not_found` on delete

## N
- [namespace.md](namespace.md) — projects as `<owner>/<slug>`: `ProjectRoute` hands routes the full name as `slug`, the route rewrite as an idempotent script; old paths answered before routing from the schema's route words (426 for the CLI, 410 otherwise), old badge and swarm addresses as 301 while served; hooks left for handle aliases and request actions; migration 0060's owner rule, its stops and its downgrade; a stale transfer go withdrawn after the rollback, renames counted from events; a slug claim locks the owner's row; transfer without step-up until the second factor (open); ending a human membership checks the namespace owner
- [notifications.md](notifications.md) — one account per address as a unique normalized column claimed under a row of `address_lock`, also by a registration's completion; a link in a mail is a signed token the hub stores nothing for, a page for a token that is not ours says nothing about anyone; notification settings store only what the human changed, the defaults fill the rest on read; items derived on every read from 30 days of the human's projects with the relations as they are now; positions sealed under a key derived from the instance key, else a stored random key; a held long-poll compares a stamp before it derives again, a few full answers at a time; deriving reads each kind of lookup once per batch

## O
- [outbound.md](outbound.md) — reads whose host comes from data resolve once and connect to the checked address; `routable()` beyond `is_global`; seams instead of a TLS server in tests

## P
- [packaging.md](packaging.md) — `src/` layout with migrations and `/help` as package data; all three drivers by default; the image's SQLite data volume; the tested set pinned with hashes via `uv pip compile --universal`; Pillow 13 for the avatar decoder (the 12.x pin superseded), the size read before Pillow; cryptography held to one major release for the stored secrets; the wheel carries the dashboard
- [persistence.md](persistence.md) — SQLAlchemy Core without the ORM; explicit migrations; at-most-one markers; value sets in the API; ids; JSON columns; UTC timestamps; utf8mb4_bin on MySQL; SQLite WAL; SQLite migrations with foreign keys off and checked; the board's card order sorted in Python and paged after the last card shown; admin-set instance settings in one table with a registry, admin-set secrets sealed in their own table; `quickstart` migrates only a new, empty SQLite database
- [placements.md](placements.md) — a preset change keeps spawn_requests and max_placements; only a `go` approves a placement proposal; a placement consent needs a human unless spawn_consent_by says role; a runner's stop revokes its agents' credentials when they are next used; a pickup's join creates a new profile at the exchange, uses the instance model (a rejoin replaces the revoked instance) and stores nothing to replay; a supervised session is not woken by what only `all` names, and `supervisor` grants nothing; an outage is stored on the placement apart from the notice it files
- [preferences.md](preferences.md) — a preference proposal's go is checked before it is answered; the human's edit travels in the proposal
- [probe.md](probe.md) — the forge probe as one worker thread per hub process, fed after reports and on an interval; a change detected where the observation is written; confirming the repository without a step-up until the second factor (open); the operator's token checked for a public repository in the one request path
- [proposals.md](proposals.md) — one `request.proposal` column and a registry of kinds with their answerer rule, not a column per kind

## Q

## R
- [releases.md](releases.md) — readiness recomputed in every write that can change it; `release_ready` gated by a stored flag
- [requests.md](requests.md) — a personal request is a request row with the asker's project, `personal` tied to `profile_owner` by a CHECK, hidden from every project route but the asker's; `to_human` a snapshot

## S
- [serving.md](serving.md) — dashboard optional unless configured explicitly, no dotfiles; local bind by default; no CDN-loaded Swagger UI; the badge template ships with the hub and only the badge and the public swarm page may choose public caching; the landing settings' PATCH alone takes a 256 KiB body; robots.txt and sitemap.xml are routes before the dashboard mount and the root's noindex is the middleware's
- [swarm.md](swarm.md) — the swarm page's window gathered once into raw facts and folded per reader (members, or agents only for the public page), kept an hour in process; an unattributed contribution only in the members' totals

## T
- [takeovers.md](takeovers.md) — the window settled lazily and by a worker, alike under the project lock; a takeover from a replaced or removed instance is cancelled
- [testing.md](testing.md) — CI matrix: full check on SQLite, tests on PostgreSQL 17 and MariaDB 11.4; MariaDB stands in for MySQL; the suite runs in parallel with a database per worker and the wheel job runs a marked subset; races on two real connections, PostgreSQL and MariaDB only
- [ticker.md](ticker.md) — a ticker item is an event with its dedupe key in a table of its own; shaped per reader where every event view is made; settings replaced key by key; merges read by the probe from the switch-on moment, sections from the diff; the forge webhook answered in the middleware before its body, only ever a trigger

## U

## V

## W

## X

## Y

## Z
