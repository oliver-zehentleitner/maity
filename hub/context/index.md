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
- [auth.md](auth.md) — a call's presence and lease side effects commit before the endpoint runs; a runner caller is confined before any route runs

## B

## C

## D

## E
- [events.md](events.md) — the long-poll waits on an asyncio event in-process, never on the database; a runner's stream reads every project it was ever attached to; mention pings counted in process, given back when the write does not commit; shared environments computed from live sessions, only announcements stored

## F

## G

## H

## I
- [images.md](images.md) — a project's logo and banner: the forge's images as rows next to the uploads, refreshed by a worker that needs no token; image routes choose their own caching; a 1 MiB cap for uploads only; avatars decoded in a self-limiting process (-I, empty environment, size from the header first); replays first, the change limit counts refused images

## J
- [joins.md](joins.md) — the join page's HTML via markdown-it-py with raw HTML off; the template shipped from docs/ into the wheel; the join host as a path rewrite in the middleware, matched on the hostname alone (fails closed); unused join links and new-profile placements lose reports_to with the removed member, the exchange keeps only an active boss

## K
- [keep-the-why.md](keep-the-why.md) — the Keep the Why export in memory: read through on request, refreshed in the background for the project view, never stored
- [kubernetes.md](kubernetes.md) — one pod with Recreate, no replica count; migrations as a pre-install/pre-upgrade hook Job; readiness on health, liveness on help; a plain Ingress with ingress-nginx defaults (retired upstream); serving only on its own schema head, no rollback downgrade

## L

## M

## N

## O
- [outbound.md](outbound.md) — reads whose host comes from data resolve once and connect to the checked address; `routable()` beyond `is_global`; seams instead of a TLS server in tests

## P
- [packaging.md](packaging.md) — `src/` layout with migrations and `/help` as package data; all three drivers by default; the image's SQLite data volume; the tested set pinned with hashes via `uv pip compile --universal`; Pillow 13 for the avatar decoder (the 12.x pin superseded), the size read before Pillow
- [persistence.md](persistence.md) — SQLAlchemy Core without the ORM; explicit migrations; at-most-one markers; value sets in the API; ids; JSON columns; UTC timestamps; utf8mb4_bin on MySQL; SQLite WAL; SQLite migrations with foreign keys off and checked; the board's card order sorted in Python and paged by position
- [placements.md](placements.md) — a preset change keeps spawn_requests and max_placements; only a `go` approves a placement proposal; a placement consent needs a human unless spawn_consent_by says role
- [probe.md](probe.md) — the forge probe as one worker thread per hub process, fed after reports and on an interval; a change detected where the observation is written

## Q

## R
- [releases.md](releases.md) — readiness recomputed in every write that can change it; `release_ready` gated by a stored flag

## S
- [serving.md](serving.md) — dashboard optional unless configured explicitly, no dotfiles; local bind by default; no CDN-loaded Swagger UI

## T
- [testing.md](testing.md) — CI matrix: full check on SQLite, tests on PostgreSQL 17 and MariaDB 11.4; MariaDB stands in for MySQL

## U

## V

## W

## X

## Y

## Z
