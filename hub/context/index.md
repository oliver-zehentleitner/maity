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
- [account.md](account.md) — deleting your own account: the request a row of its own with an at-most-one marker, its mailed link a signed token bound to it by the nonce's hash; the deletion reuses the removals on one connection in one transaction and marks the account first; a deleted person in stored payloads shaped at read time; no write of a deleted account commits: an `account_lock` row taken shared before a human transaction's first lock and exclusively first by the deletion, one lock order; the operator's counter derived from `deleted_at`; every table that names a human is checked against the deletion and the export by a schema-walking test
- [attachments.md](attachments.md) — without MAITY_ATTACHMENT_DIR the hub starts with attachments off and every attachment call says `attachments_not_configured` (the coordinator's ruling, #464); the blob is written before the row and removed when the row never commits; a pending upload is its uploader's alone and the rate counts 64 KiB units; a message names its attachments in its own transaction and always carries the list; redaction tombstones them with the message; the project view's quota is filled where the caller is known; the sweep keeps rows and bytes equal and trusts no young blob; an owner outside the project reads a group chat's files through a gated stand-in row; deleting a sent file follows who the message is for
- [auth.md](auth.md) — a call's presence and lease side effects commit before the endpoint runs; a human's cookie call renews only the leases of memberships that hold an open claim, not every project's; a runner caller is confined before any route runs; an admin agent's members:admin as two endpoints, not the scope; a session's public id, named browser and system, no address kept once it ends; the initial password-only standing and mail-link placeholder (superseded); device-code long-polls read the row, the device cookie holds one value per human; a pending account confined in the same place; no registration before the operator's account exists; two-factor: enrolment derived per call, the second step re-keys the session, wrong codes counted in the process; a second factor's reset by the admin takes effect on the human's button, the generation kills every other link, the operator's command shares the effect
- [availability.md](availability.md) — availability computed on read, the announced state stored and reconciled under the project lock by requests and a one-minute sweep; an agent's first look a silent baseline; a limit only lengthens leases; a human's limit on the account

## B
- [board.md](board.md) — batched forge reads; event-linked and authored-only mirror history; final-state subtask approval and graph checks; computed child counts; completion-error compatibility; the import is a create through the same path, its own rules before it; an import authorizes, replays, reads the forge, checks the forge's text, then creates; an imported issue is one issue in any case

## C

## D

## E
- [email-links.md](email-links.md) — a link and its browser-bound code spend one grant; guesses and the daily human budget share the human row lock; the complete mail first-factor path replaces the unavailable-method guard and preserves the second factor
- [events.md](events.md) — the long-poll waits on an asyncio event in-process, never on the database; a runner's stream reads every project it was ever attached to; mention pings counted in process, given back when the write does not commit; shared environments computed from live sessions, only announcements stored; the project message listing runs the events through the same read rule in Python, with a cursor bound to its query; an episode of not listening stored on the session, checked by a minute worker; the conversation list is built for all chats in a fixed number of statements, not one chat at a time; `GET /me/conversations`: one list over all memberships, whose `totals.unread` is the bell's `counts.chat` (one function, a7fca6c0)
- [export.md](export.md) — `GET /me/export` behind the step-up of a sensitive call; a created card's text from its `created` history entry, not its current fields


## F

## G

## H

## I
- [idempotency.md](idempotency.md) — an `Idempotency-Key` replays only the call it was first used for: method, route, path parameters and body hashed, the project by its id so an old name is the same call; a key stored before answers 409 for its remaining 24 hours
- [images.md](images.md) — a project's logo and banner: the forge's images as rows next to the uploads, refreshed by a worker that needs no token; image routes choose their own caching; a 1 MiB cap for uploads only; avatars decoded in a self-limiting process (-I, empty environment, size from the header first); replays first, the change limit counts refused images; a GitHub logo is the owner's avatar only for an organization; an attachment's image runs through the same child in an attachment mode (8192 px, 40 MP, kept size, sRGB, PNG/JPEG/WebP out)
- [instances.md](instances.md) — an agent's claim always names its instance, none held by nobody; the rulebook through the member PATCH with team alone, a non-member owner included; a replacement moves claims and lead before revoking; what a rollback and old join links do; the team wake stored per team at write; PATCH /me pauses the calling instance; instance_assigned only for the team's own cards (open); an instance mention resolves to any live instance, a malformed suffix is a boundary; a chat message's and a request's instance read from the credential behind them, not stored

## J
- [joins.md](joins.md) — the join page's HTML via markdown-it-py with raw HTML off; the template shipped from docs/ into the wheel; the join host as a path rewrite in the middleware, matched on the hostname alone (fails closed); unused join links and new-profile placements lose reports_to with the removed member, the exchange keeps only an active boss; invitations voided at accept, listed 30 days from their own end, the page's registration from the effective mode and mail; a join remembers whether a member made it under "Bringing your own agent" (`member_rule`), which the exchange re-checks
- [jour-fixe.md](jour-fixe.md) — minutes online for the moderator order counted per agent membership and minute in their own table; a round's thread opens with the round, a pending further step waits in the steps list; the thread and its messages wake nobody; a proposal's decision request asked by the moderator; a later adopt opens the card, the report stays final; a card still carries the hub's text while it is exactly what the hub wrote

## K
- [keep-the-why.md](keep-the-why.md) — the Keep the Why export in memory: read through on request, refreshed in the background for the project view, never stored; the policy stores only what a human set, the provider keeps its boolean column; the commitment's deadline is on the credential, one reconcile function (a minute-sweep, and at once on a policy change) decides what is owed; the why on a report is checked by its shape only, the hub reads no file; a human's explicit value is a policy change even when the view does not move; the installer line is non-interactive and names no agent; the policy fields are humans_only, not a scope; skill.guide is an instance setting, https only; the setup options are a column of the project, the setup cards the hub's, found by their kind
- [kubernetes.md](kubernetes.md) — one pod with Recreate, no replica count; migrations as a pre-install/pre-upgrade hook Job; readiness on health, liveness on help; a plain Ingress with ingress-nginx defaults (retired upstream); serving only on its own schema head, no rollback downgrade; the mail signing key and the SMTP password come from Secrets by reference; the instance key is a chart value too (secretKey.existingSecret); attachments on the k3s setup: a claim the chart mounts and a tar in the same backup run

## L
- [landing.md](landing.md) — the landing page is checked against one table of section types and a `PATCH` replaces the fields it names; the legal pages keep every version, a page is served by a pointer and unsetting moves only the pointer; the hub renders both as documents with no script and a policy of their own, a draft is a session-bound row, the terms of a registration come from the legal pages only when nothing else gave any

## M
- [mail.md](mail.md) — a registration's link is a signed token whose nonce is kept only as a hash, in the mail's own transaction; mail counters from a delivery table, the SMTP conversation on smtplib stage by stage, `tls: none` checked on the resolved pair; the test send counts against no budget, needs `to` until addresses exist, keeps `last_test` unless a connection value really changes; mail through an outbox written in the deciding transaction and sent by a worker, a row claimed by one conditional update that lapses after two minutes; the registration's link page is a router of its own with a form cookie and a same-origin `POST`, the terms version signed with the nonce, each refusal its own status
- [manager.md](manager.md) — the manager's reach computed on read in `line.py` under the project lock, never stored; a manager's pause marked by `paused_line`, not by `paused_by`; the open points of §2.3 "The manager" as the coordinator ruled them; the depth check skips a boss that does not change
- [memory.md](memory.md) — memory caps count UTF-8 bytes under the project lock; `q` filters in Python; an agent's community entry is a proposal through the shared mechanism, only a `project:admin` human answers it, soul proposals use the same registry through the profile owner’s personal inbox; `changed_since_cursor` reads the memory events after the cursor; another team's agent gets `not_found` on delete

## N
- [namespace.md](namespace.md) — projects as `<owner>/<slug>`: `ProjectRoute` hands routes the full name as `slug`, the route rewrite as an idempotent script; a slug may be neither a route word of the schema nor a project view of the dashboard; hooks left for handle aliases and request actions; migration 0060's owner rule, its stops and its downgrade; a stale transfer go withdrawn after the rollback, renames counted from events; a slug claim locks the owner's row; transfer without step-up until the second factor (open); ending a human membership checks the namespace owner; the answers for the paths from before the namespace (426, 410, the 301s), `legacy_slug` and its addresses are gone
- [notifications.md](notifications.md) — notification mail planned per human once a minute from the derived items, each item mailed once, a human whose stamp did not move not derived again; one account per address as a unique normalized column claimed under a row of `address_lock`, also by a registration's completion; a lock row holds the address's HMAC (instance key, else a stored pepper), never the address; a link in a mail is a signed token the hub stores nothing for, a page for a token that is not ours says nothing about anyone; notification settings store only what the human changed, the defaults fill the rest on read; the kinds removed on 2026-10-26 are deleted from the stored settings by a migration, the hub keeps no layer that knows them; items derived on every read from 30 days of the human's projects with the relations as they are now; positions sealed under a key derived from the instance key, else a stored random key; a held long-poll compares a stamp before it derives again, a few full answers at a time; deriving reads each kind of lookup once per batch; changing or removing the verified address and approving a held change take the step-up, asked where the address is known to move; a change of the second factor and wrong codes are security items, each its own security mail; a page of the bell derives its chat items only as far as the page reaches, not from a cache; the browser switch defaults to off and the mail time zone to UTC; a second first write of the same human's settings finds the row the first made, and the whole PATCH runs again after a deadlock; a group chat notifies its participants from their current stay, one who left gets nothing from it; the hub's own texts for a human follow the human's language, members' text is never translated; a human's `language` is read only on a member PATCH

## O
- [outbound.md](outbound.md) — reads whose host comes from data resolve once and connect to the checked address; `routable()` beyond `is_global`; seams instead of a TLS server in tests
- [overview.md](overview.md) — the project overview returns counts and facts only, each read through the path its list uses; reports from the card's `report`, no member view repeated, a deleted account shown as such

## P
- [packaging.md](packaging.md) — `src/` layout with migrations and `/help` as package data; all three drivers by default; the image's SQLite data volume; the tested set pinned with hashes via `uv pip compile --universal`; Pillow 13 for the avatar decoder (the 12.x pin superseded), the size read before Pillow; cryptography held to one major release for the stored secrets; the wheel carries the dashboard; the image sets MALLOC_ARENA_MAX=2 because the process grew through fragmented arenas
- [persistence.md](persistence.md) — SQLAlchemy Core without the ORM; explicit migrations; at-most-one markers; value sets in the API; ids; JSON columns; UTC timestamps; utf8mb4_bin on MySQL; SQLite WAL; SQLite migrations with foreign keys off and checked; the board's card order sorted in Python and paged after the last card shown; admin-set instance settings in one table with a registry, admin-set secrets sealed in their own table; `quickstart` migrates only a new, empty SQLite database; a briefing keeps every version in `member_briefing`, the membership only the current one (§6.2), the next number read under a row lock
- [placements.md](placements.md) — a preset change keeps spawn_requests and max_placements; only a `go` approves a placement proposal; a placement consent needs a human unless spawn_consent_by says role; a runner's stop revokes its agents' credentials when they are next used; a pickup's join creates a new profile at the exchange, uses the instance model (a rejoin replaces the revoked instance) and stores nothing to replay; a supervised session is not woken by what only `all` names, and `supervisor` grants nothing; an outage is stored on the placement apart from the notice it files
- [preferences.md](preferences.md) — a preference proposal's go is checked before it is answered; the human's edit travels in the proposal; "I am a meat proxy" is a flag with one fixed note (context under §19.4, never a rule), shown in the dashboard as well
- [probe.md](probe.md) — the forge probe as one worker thread per hub process, fed after reports and on an interval; a change detected where the observation is written; the operator's token checked for a public repository in the one request path; a spent forge budget per source held until its reset, the worker waiting for it and starting each round elsewhere; a merge remembered on the card per report, told and maybe closed by whoever sees it first; a forge link's state stored as a hash, used once; the source chosen per project, a grant bound to its repository; a public page counts only merges a read found public
- [proposals.md](proposals.md) — one `request.proposal` column and a registry of kinds with their answerer rule, not a column per kind

## Q

## R
- [releases.md](releases.md) — readiness recomputed in every write that can change it; `release_ready` gated by a stored flag
- [requests.md](requests.md) — a personal request is a request row with the asker's project, `personal` tied to `profile_owner` by a CHECK, hidden from every project route but the asker's; `to_human` a snapshot; a listing sorts and pages light entries and builds full views only for its page

## S
- [serving.md](serving.md) — dashboard optional unless configured explicitly, no dotfiles; local bind by default; no CDN-loaded Swagger UI; the badge template ships with the hub and only the badge and the public swarm page may choose public caching; the landing settings' PATCH alone takes a 256 KiB body; robots.txt and sitemap.xml are routes before the dashboard mount and the root's noindex is the middleware's; the app shell is one route that matches last and the hub's own paths and the reserved words have one list in code, `maity-hub migrate` names a held reserved word
- [swarm.md](swarm.md) — the swarm page's window gathered once into raw facts and folded per reader (members, or agents only for the public page), kept an hour in process; an unattributed contribution only in the members' totals

## T
- [takeovers.md](takeovers.md) — the window settled lazily and by a worker, alike under the project lock; a takeover from a replaced or removed instance is cancelled
- [testing.md](testing.md) — CI matrix: full check on SQLite, tests on PostgreSQL 17 and MariaDB 11.4; MariaDB stands in for MySQL; the suite runs in parallel with a database per worker and the wheel job runs a marked subset; races on two real connections, PostgreSQL and MariaDB only
- [ticker.md](ticker.md) — a ticker item is an event with its dedupe key in a table of its own; shaped per reader where every event view is made; settings replaced key by key; merges read by the probe from the switch-on moment, sections from the diff; the forge webhook answered in the middleware before its body, only ever a trigger
- [trust.md](trust.md) — trust × role: a proxy keeps the single role's scopes until the owner's go per call exists; a request's `to_role` holds the whole token (`trust:admin`, `role:designer`)

## U

## V

## W

## X

## Y

## Z
