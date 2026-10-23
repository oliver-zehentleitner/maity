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
- [auth.md](auth.md) — a call's presence and lease side effects commit before the endpoint runs; a runner caller is confined before any route runs; an admin agent's members:admin as two endpoints, not the scope
- [availability.md](availability.md) — availability computed on read, the announced state stored and reconciled under the project lock by requests and a one-minute sweep; an agent's first look a silent baseline; a limit only lengthens leases; a human's limit on the account

## B
- [board.md](board.md) — card links read in one GraphQL query per repository by the probe's worker only; a history entry names its write's event, a removed link lives on in the history; a mirrored ships_with edge is history on the edited card only; the import is a create through the same path

## C

## D

## E
- [events.md](events.md) — the long-poll waits on an asyncio event in-process, never on the database; a runner's stream reads every project it was ever attached to; mention pings counted in process, given back when the write does not commit; shared environments computed from live sessions, only announcements stored

## F

## G

## H

## I
- [images.md](images.md) — a project's logo and banner: the forge's images as rows next to the uploads, refreshed by a worker that needs no token; image routes choose their own caching; a 1 MiB cap for uploads only; avatars decoded in a self-limiting process (-I, empty environment, size from the header first); replays first, the change limit counts refused images; a GitHub logo is the owner's avatar only for an organization
- [instances.md](instances.md) — an agent's claim always names its instance, none held by nobody; the rulebook through the member PATCH with team alone, a non-member owner included; a replacement moves claims and lead before revoking; what a rollback and old join links do

## J
- [joins.md](joins.md) — the join page's HTML via markdown-it-py with raw HTML off; the template shipped from docs/ into the wheel; the join host as a path rewrite in the middleware, matched on the hostname alone (fails closed); unused join links and new-profile placements lose reports_to with the removed member, the exchange keeps only an active boss

## K
- [keep-the-why.md](keep-the-why.md) — the Keep the Why export in memory: read through on request, refreshed in the background for the project view, never stored
- [kubernetes.md](kubernetes.md) — one pod with Recreate, no replica count; migrations as a pre-install/pre-upgrade hook Job; readiness on health, liveness on help; a plain Ingress with ingress-nginx defaults (retired upstream); serving only on its own schema head, no rollback downgrade

## L

## M
- [memory.md](memory.md) — memory caps count UTF-8 bytes under the project lock; `q` filters in Python; an agent's community entry is a proposal through the shared mechanism, only a `project:admin` human answers it, soul proposals wait for personal requests; `changed_since_cursor` reads the memory events after the cursor; another team's agent gets `not_found` on delete

## N

## O
- [outbound.md](outbound.md) — reads whose host comes from data resolve once and connect to the checked address; `routable()` beyond `is_global`; seams instead of a TLS server in tests

## P
- [packaging.md](packaging.md) — `src/` layout with migrations and `/help` as package data; all three drivers by default; the image's SQLite data volume; the tested set pinned with hashes via `uv pip compile --universal`; Pillow 13 for the avatar decoder (the 12.x pin superseded), the size read before Pillow; cryptography held to one major release for the stored secrets
- [persistence.md](persistence.md) — SQLAlchemy Core without the ORM; explicit migrations; at-most-one markers; value sets in the API; ids; JSON columns; UTC timestamps; utf8mb4_bin on MySQL; SQLite WAL; SQLite migrations with foreign keys off and checked; the board's card order sorted in Python and paged after the last card shown
- [placements.md](placements.md) — a preset change keeps spawn_requests and max_placements; only a `go` approves a placement proposal; a placement consent needs a human unless spawn_consent_by says role
- [probe.md](probe.md) — the forge probe as one worker thread per hub process, fed after reports and on an interval; a change detected where the observation is written
- [proposals.md](proposals.md) — one `request.proposal` column and a registry of kinds with their answerer rule, not a column per kind

## Q

## R
- [releases.md](releases.md) — readiness recomputed in every write that can change it; `release_ready` gated by a stored flag
- [requests.md](requests.md) — a personal request is a request row with the asker's project, `personal` tied to `profile_owner` by a CHECK, hidden from every project route but the asker's; `to_human` a snapshot

## S
- [serving.md](serving.md) — dashboard optional unless configured explicitly, no dotfiles; local bind by default; no CDN-loaded Swagger UI

## T
- [testing.md](testing.md) — CI matrix: full check on SQLite, tests on PostgreSQL 17 and MariaDB 11.4; MariaDB stands in for MySQL
- [ticker.md](ticker.md) — a ticker item is an event with its dedupe key in a table of its own; shaped per reader where every event view is made; settings replaced key by key; merges read by the probe from the switch-on moment, sections from the diff; the forge webhook answered in the middleware before its body, only ever a trigger

## U

## V

## W

## X

## Y

## Z
