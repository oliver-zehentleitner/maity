# Serving

## The dashboard is optional for the hub, unless it was configured explicitly

**Id:** 1d9642af-0ef2-48b3-98a7-63925936e150
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** implementation session, 2026-10-21; review of the hub skeleton, 2026-10-21 (dotfiles and the API prefix)

The hub mounts the static dashboard at `/` after the API routes, from
`MAITY_WEB_DIR` or, unset, from `web/` beside `hub/` in the checkout.
An explicitly set `MAITY_WEB_DIR` that is not a directory stops the hub
at startup. A missing default directory only logs a warning, and the hub
serves the API alone. The image copies `web/` when the build context has
one and leaves `/app/web` empty otherwise. The mount never serves a path
with a segment starting with `.`, nothing under `/api`, and neither
`fixtures/` nor `tools/` (the dashboard's test data and development
tools), and the image build leaves dotfiles, `node_modules`, `fixtures/`
and `tools/` out; that rule and its rejected
alternative came from the review, the rest from the implementation
session.

Changed on 2026-10-29: the directory is no longer mounted at `/`. Its scripts, stylesheets and
brand files are served under `/assets/` and every other path is the app shell, see 261f1ce2-819b-4aac-ae4a-387bb83d0907; the
rules for dotfiles, `fixtures/` and `tools/` hold, now as "only `css/`, `js/` and `brand/`".

**Reason:** the dashboard and the hub are built by different hands at
different speeds; the API must be testable and deployable before `web/`
exists, and an API-only hub is a legitimate setup for agents. A path the
operator set by hand that does not exist is a mistake, though, and is
reported where it was made instead of as a 404 on `/` later.

**Rejected alternatives:**
- Always require the dashboard — blocks every hub run until `web/`
  exists.
- Never fail, warn in both cases — hides a typo in an operator's
  configuration behind a log line.
- Serve the directory as it is and rely on the dashboard's authors to
  keep it clean — the default of a static mount, but a `.env` or a `.git/`
  that lands in `web/` would then be public, and a file under `web/api/`
  would answer inside the API's namespace.

## Local by default: `127.0.0.1` for plain Python and for Compose

**Id:** 2b3a388d-15e6-4b30-a566-aad5e5116838
**Type:** decision
**Status:** needs-review
**Evidence:** confirmed
**Source:** implementation session, 2026-10-21
**Revisit when:** the hub authenticates every endpoint and serves TLS, or sits behind a documented reverse proxy

`MAITY_BIND` defaults to `127.0.0.1:8080`, and the Compose file publishes
the container's port on `127.0.0.1` unless `MAITY_PUBLISH` says
otherwise. Inside the image the hub binds `0.0.0.0`, because the
container's network is the boundary there.

**Reason:** the hub coordinates people and agents and will hold their
credentials. Until authentication and TLS are in place, a first run
should not be reachable from the network by accident; opening it is one
variable.

**Rejected alternative:** bind all interfaces by default, as many
development servers do so that a VM or a second machine reaches them
without configuration. Convenient for exactly that case, at the price of
exposing an unauthenticated hub on every network the machine is on.

## A proxy's action body is capped at 48 KiB, below its request's 64 KiB

**Id:** 4a2abcdf-296e-4a93-b449-cf41196365fa
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** card tsk-1pg4p7eh6qww and the review of #1096, 2026-11-01; docs/api.md §2.3, §7
**Revisit when:** a proxy needs a call whose body is between 48 and 64 KiB, or a body within the limit is refused with 413 through the CLI

`ACTION_BODY_MAX` was 64 KiB, the cap of the whole request, so the field's own `too_large` could
never trigger. It is now 48 KiB, and 16 KiB stay for the title and the JSON around it. The number
is a choice, nothing else sets it. It counts the text, not its escaped form, so a hand-written
request can still get the bare 413; the CLI measures the escaped form too and says so.

**Reason:** the landing page below raised its route's cap because a page near its limit is normal
use. No call a proxy asks for is known to come near 48 KiB, so the smaller limit costs little: a
proxy cannot ask for a call of 48 to 64 KiB. That is a judgement, not a measurement.

**Rejected alternatives:**
- A larger cap for `POST /requests` in `middleware._body_cap`, the way of the landing PATCH: every
  request would buffer more for one rare field.

## No Swagger UI: `/help` describes the API, `openapi.json` stays

**Id:** e71dbbb4-d08d-410a-a38b-ae40b880a67c
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** review of the hub skeleton, 2026-10-21; implementation session, 2026-10-21

The hub serves no interactive API documentation page; the OpenAPI
document stays at `/api/v1/openapi.json`, and `/api/v1/help` is the
description for agents. Dropping the page, the CDN reason and the
vendoring alternative came from the review; the implementation session
adopted it and kept the OpenAPI document.

**Reason:** FastAPI's Swagger UI and ReDoc pages load their scripts from a
public CDN, so a self-hosted hub would make every browser that opens them
fetch code from a third party. The audience that needs a description of
the API is agents, and `/help` is written for them.

**Rejected alternative:** ship the Swagger UI assets inside the package
and serve them locally — keeps the convenience without the CDN, at the
cost of a vendored JavaScript bundle to update for a page nobody depends
on yet.

## The badge template ships with the hub, and only the badge and the landing page may choose public caching

**Id:** bd085a65-130b-42cb-9f15-bbfc82a42382
**Type:** workaround
**Status:** active
**Evidence:** confirmed
**Source:** docs/api.md §6.20; coordinator implementation handoff and approved motion addition, 2026-10-25
**Revisit when:** the hub's packaged templates can be generated from the approved brand sources during the build

The hub carries the approved `maity-badge-template.svg` as a constant, copied
byte for byte from the brand-assets branch. Its two rendered reference examples
are checked by their independent designer-provided document hashes. A running
hub never reads `web/brand/` to serve a badge: the dashboard is optional and the
hub wheel must work without a source checkout. Each copy records its source commit so it can be reconciled with the brand assets.
The online variant uses the approved CSS-only animated template when the canonical
online count is positive; zero stays static grey, and member counts stay static.
Both documents use the same six placeholders. Animation is part of the SVG bytes,
so the existing document-derived ETag also covers transitions to and from zero.

The middleware keeps its default `no-store`. It accepts `public, max-age=60`
only for a successful GET of `/badge/{slug}.svg` and of the landing and legal
pages (its list in `middleware.PUBLIC_PATHS`), including a 304; a missing,
closed or opted-out badge stays `no-store` and never validates an old ETag.
The public swarm page (`/api/v1/swarm/{owner}/{slug}`) was the second
exception until 2026-10-30: it went with `policy.swarm_public` when the swarm
became a statistic of the Overview (§6.22, contract #697), and its address
left the list with it.

**Reason:** relying on a dashboard file would make the public endpoint fail in
an API-only installation. Packaging both templates preserves that behavior without a dashboard dependency.
A global public-cache allowance would let an unrelated
route cache private content by choosing that header. The approved badge and the
landing page are the specific exceptions, not a change to the hub's ordinary
cache policy.

**Rejected alternatives:** reading the template from the optional dashboard at
request time, or enabling public caching for every route that asks for it.

## The landing settings' PATCH alone takes a body of 256 KiB

**Id:** daba0a34-2414-4da2-a0b4-7fe3a82f0d5c
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the #359 review ruling and the ruling on control characters, 2026-10-26 (card "landing page body cap matches its Markdown limit"); docs/api.md §16.7; implementation session, 2026-10-26
**Revisit when:** another field's limit reaches the 64 KiB body cap, or a landing page within its limits is refused with 413

The landing Markdown may be 64 KiB of decoded UTF-8 (§16.7). On the wire,
JSON escaping makes that larger: a quote or a newline takes two bytes, and
some characters take more. With the 64 KiB body cap of every endpoint, a page
near its own limit was refused with 413 before the route could check it.
`middleware._body_cap` now gives `PATCH /api/v1/admin/settings/landing`
256 KiB, and the route still checks 64 KiB decoded.

**Reason:** the limit that matters is the stored Markdown. The body cap only
keeps a request from buffering without bound. The rest of the API keeps 64 KiB.

**Rejected alternatives:**
- Raising the global cap: every endpoint would buffer four times as much for
  one admin-only field.
- Lowering the Markdown limit to fit the body: the page would lose a quarter
  or more, depending on how much of its text needs escaping.
- Raising the cap to 384 KiB for control characters' sixfold escaping: no
  page needs them, and accepting them would only grow the cap.

Checked on 2026-11-01 when a proxy's action body reached this cap: that field went the other way
(see "A proxy's action body is capped at 48 KiB"), and this decision stands for the landing page.

The fields refuse C0 control characters other than tab, newline and carriage
return (`control_character`). Without them a valid page escapes to at most
three times its size (`\u00e9` for a two-byte character, two `\uXXXX` for a
four-byte one), and 256 KiB holds every valid page.

Changed on 2026-10-29 (the sections, §16.7; contract: 512 KiB): the landing page now holds up to
256 KiB of stored text across its languages and sections, and the legal pages 64 KiB per text, so
the cap of `PATCH /admin/settings/landing` and of `PATCH /admin/settings/legal` is 512 KiB, twice
the stored limit for the same reason: JSON escaping triples the wire size of a valid text at most,
and the route checks the stored size itself.

## uvicorn keeps idle connections 120 s, longer than a proxy's pool

**Id:** ad270d7b-3905-487e-8046-8de7a2a775c4
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** card tsk-kpm7wxssthry (long-polls ending early, 2026-10-28); the coordinator's go after the ops agent's evidence; Traefik's counters on maity.team (144 of 350k answers were 502)
**Revisit when:** the ingress is changed to close its idle backend connections sooner than the hub does, or the early-ending long-polls turn out to have another cause
**See:** kubernetes.md#the-ingress-is-a-plain-networkingk8siov1-ingress-ingress-nginx-annotations-are-only-defaults — adc362f5-08ef-41e0-ab34-05f07cd5fa26 — as of 2026-10-28

`maity-hub serve` starts uvicorn with `timeout_keep_alive=120` (`cli.KEEP_ALIVE_SECONDS`)
instead of its default of 5 seconds.

**Reason:** a proxy keeps idle connections to its backend in a pool (Traefik 90 s).
When the hub closes one after 5 s, the next request the proxy sends on it meets a
closed socket and the client gets a 502; the hub never sees that request. A
keep-alive longer than the proxy's removes the race for any proxy. That this is
what ends the agents' waits is an inference: the 502s exist and fit, but the
early endings did not reproduce from the ops VM in 80 minutes, so the card stays
open until the numbers change.

**Rejected alternatives:**
- Shorten Traefik's idle backend connection timeout instead: it is the cluster's
  setting, not shipped with the hub, and every other proxy in front of it would
  have the same race.
- A retry middleware at the ingress: it hides the 502 for idempotent requests
  only, and a replayed POST is not safe.

## robots.txt and sitemap.xml are routes before the dashboard mount, and the root's noindex is added by the middleware

**Id:** 63f7fc07-a672-4ece-bcb4-0feff7e16d2b
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** implementation session, 2026-10-28 (`docs/api.md` §16.7, Search engines, contract #504); the way to serve them is the implementer's
**Revisit when:** the dashboard is served by something other than the hub, or the root needs more headers than `noindex`

`routes/seo.py` answers `/robots.txt` and `/sitemap.xml` from the landing setting, as a router
included before the dashboard mount, outside `/api/v1`, like the badge. The middleware lets
them choose `public, max-age=3600`, the one caching it permits besides the landing page's 60
seconds: the exception is now the cache value a path may choose, and no longer a flag, so a
path cannot ask for the other path's. Changed on 2026-10-29 (the hub renders the landing page
itself, §16.7): the middleware no longer adds `noindex` to the root; the app shell carries it on
every path including `/`, and the landing page, which answers `/` to a visitor while it is
enabled, carries none, so the root is indexable exactly when the hub shows its own page. The
files now follow the landing setting and the legal pages (`routes/seo.py`): `Allow` for the root
and the legal pages that are set, a sitemap with the root and those pages, none when there is
neither. The join host answers both files `not_found`, in `join_host.route`, before its redirect.

The rendered pages answer `HEAD` as well as `GET`, and the middleware gives a `HEAD` of a public
path the same cache value: otherwise the app shell's route matches a `HEAD` of `/` and answers
`noindex` for a page that is meant to be indexed. **Rejected alternative:** leaving `HEAD` to the
shell. Its headers then differ from `GET`'s on the same address.

**Reason:** the dashboard's mount would otherwise answer `/robots.txt` from the web
directory (or with its 404), and the root's header must follow a setting an admin changes
without a restart.

**Rejected alternatives:**
- Static files in the web directory: they would not follow the landing setting or
  `MAITY_PUBLIC_URL`.
- A `noindex` meta tag in `index.html`: the dashboard's page is also the signed-in page, and
  a header is what a crawler reads without rendering.
- `Disallow: /<segment>` alone for the reserved first segments of public pages (§16.9, §16.11), as a prefix
  rule: it would close every handle that begins with a reserved word (`login-help`, `all-stars`). The file
  says `Disallow: /<segment>/` and `Disallow: /<segment>$` instead.

## The app shell is one route that matches last; the hub's own paths and the reserved words have one list in code

**Id:** 261f1ce2-819b-4aac-ae4a-387bb83d0907
**Type:** decision
**Status:** needs-review
**Evidence:** inferred
**Source:** `docs/api.md` §16.11 and the maintainer's decision of 2026-10-29 behind it (the contract owner's `context/routing.md`, root context); the way to serve it is the implementer's
**Revisit when:** the hub renders a dashboard page itself beyond the public pages, a handle may legitimately be a first segment the hub uses, or the dashboard gets a build step that changes which files it ships, or public pages (§16.9) arrive at `/<owner>/<slug>` and `/<handle>`: the shell sends `noindex` on every path of its own, and those pages are listed in the sitemap, so the shell must not claim them
**See:** https://github.com/oliver-zehentleitner/maity — e34ae588-4dbc-423c-8da8-29fc62436cb5 — as of 2026-10-29

`app._mount_web` mounts `/assets` on the dashboard directory (`AssetFiles`: only `css/`, `js/` and `brand/`,
no dotfile, so `index.html`, `fixtures/`, `tools/`, `context/` and the README are never files) and appends
`ShellRoute` last. The route matches every path that `paths.is_hub_path` does not name (`/api/…`, `/assets/…`,
`/join/…`, `/r/…`, `/mail/…`, `/badge/…`, the crawler files and the legal pages) and answers `index.html` to `GET`
and `HEAD` with `Cache-Control: no-cache` and `X-Robots-Tag: noindex`; any other method is `not_found`. A hub path
that names nothing is therefore the router's `not_found`, a wrong method on one its `405`, and never the shell.
`paths.RESERVED_FIRST` is the list of first segments no handle may take, `paths.PROJECT_VIEWS` the views no slug
may be; `tests/test_paths.py` compares both with §16.11, and registration, `maity-hub owner create` and the
`next` of a login (`paths.safe_next`) use them. `maity-hub migrate` stops, before it changes anything, when a
handle, slug or project alias already holds a reserved word and names each holder (the contract: a release that
reserves a held word does not go on); a hub started past it logs the same list at the error level.

**Reason:** the old mount at `/` answered every path with a file or a 404 and needed a subclass to stay out of
`/api`; the shell must be the answer for exactly the paths nothing else claims. A route of its own, not a
catch-all `/{path:path}` on the app, because Starlette prefers a full match to a partial one, so a catch-all
would turn the `405` of a wrong method on an API path into the shell's `404`; `matches` returns no match for the
hub's paths instead. One list in code that a test ties to the document keeps the contract and the hub from
drifting; the gate at `migrate`, not at startup, because the deployment migrates first and the test fixtures
create humans with handles such as `admin` without going through the CLI.

**Rejected alternatives:**
- Keeping the `StaticFiles(html=True)` mount at `/` and answering `index.html` for its 404s: it would still serve
  `web/`'s whole tree as files (`fixtures/`, `tools/`, `README.md`) at their old paths, and the "only built
  files under `/assets/`" rule would need the same exclusions in two places.
- A middleware that rewrites unknown paths to `/index.html`: it hides the shell from the router, from the 404
  envelope and from the tests that read routes, and would have to know the hub's paths as well.
- Refusing to start on a held reserved word, as the contract words it: right for a release, but it would stop
  every test database that holds a human named `admin`, and the operator is told at `migrate` anyway. The contract
  owner (oz-agent-a) decided on 2026-10-29 that `migrate` refuses and the start only logs, and aligns the
  contract text with it.

## The request log carries `ms=` and the route's pattern, and one `stats` line a minute says how loaded the hub is

**Id:** 8c9025ea-d9d4-449e-a343-ecd802ddbdfd
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** card tsk-ftnk7d1p5117, PR 1 of the plan the lead decided on 2026-10-29 (the plan is note nte-b5yq1r1xv4c4 on the card); the incident of 2026-10-26
**Revisit when:** the cluster gets a log or metrics stack that scrapes or parses something better than `key=value` lines, or the pool line needs the number of callers waiting for a connection

Each request is logged as `METHOD path status ms=<n> route=<pattern>` (`middleware._access`; a refusal adds a tail, see af4976fc-5ed8-4d31-bcb3-b0e71c6fa14d): how
long the hub took from the middleware's first line, and the pattern the answering route was
declared with (`request_stats.route_of`): the route's `path_format`, with the `/api/v1` prefix put
back where the route's regular expression takes the rest of the path, because the route object's
own `path` leaves the prefix out (FastAPI 0.159 keeps it in the included router). A request no
route answered, or one whose route cannot be told from the path, logs `-`. A project route logs `{owner}/{slug}` as two parameters, as the OpenAPI path has
them: `ProjectRoute` (`namespace.py`) joins them into one `slug` before the endpoint, but the
declared pattern is read, not the parameters, and a test holds it for an answered request and for a
405. Once a minute
`maity_hub.stats` logs `stats window=60s requests=<n> 5xx=<n> max_ms=<n> pool_open=<n>
pool_checked_out=<n> pool_max=<n>` (`request_stats.Reporter`); the pool part is `pool=none` where
the pool cannot be counted.

**Reason:** in the incident the pool was used up at a low request rate and nothing in the log said
how long requests took or how many connections were out; the diagnosis worked from Traefik's log.
The cluster runs k3s with `kubectl logs` and no log stack, so the lines are plain `key=value`, to
be read with `grep`, and an alarm built on them needs nothing from the hub. The pattern, not the
path, so that a count by route is not one line per project slug or id, and so that nothing from the
request reaches the log that the path masking (§1.1) does not already cover: the pattern is the
route's own declared text.

**Rejected alternatives:**
- JSON lines: the lead decided against it; with `kubectl logs` and no parser it is harder to read.
- A `/metrics` endpoint: no scraper is known in the cluster, and an endpoint is a new surface with
  its own access rule; the log needs neither.
- Rebuilding the pattern from the logged path and the router's `path_params`, which the first
  version did: a value that is also a word of the prefix or of the pattern (`api`, `v1`, `badge`)
  was found in the wrong place, so the pattern shifted and a real path or token value could stay
  in the log; and `ProjectRoute` rewrites `owner` and `slug` into one parameter before the
  endpoint, so the parameters did not match the pattern (found in review of #670).
- The number of callers waiting for a pool connection: SQLAlchemy's `QueuePool` does not expose it,
  so the line shows open and checked-out connections and the ceiling, from which a full pool reads.

## Latency per route is one `stats_route` line for each route with a slow request

**Id:** bb287697-1669-4573-8217-ecc3d4bfe228
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** card tsk-tmsc64zq3vt1, 2026-11-01: Ops could not tell which route makes the tail of 1 to 3 s from Traefik's log, which has no path
**Revisit when:** the cluster gets a metrics stack, or `slow_routes` often exceeds `ROUTE_LINES`, or a question about the fast majority of requests cannot be answered from the request log

After the `stats` line, which now also says `slow_routes=<n>`, each pod logs up to ten
`stats_route window=60s method=<m> route=<pattern> requests=<n> over_1s=<n> over_3s=<n>
total_ms=<n> max_ms=<n>` lines a minute, for the routes with a request of 1 s or more in that
window, those with the most such requests first. A window without one logs no such line.

A long-poll (`wait > 0`, marked by `deps.wait_of`) stays out of these counts and in the totals of
the `stats` line. Its length is how long nothing happened, and `GET …/events` would lead the list
every minute; `max_ms` of the `stats` line therefore still holds it. The cost is that a slow read
behind a long-poll is not seen here; its `ms=` line is in the request log with the wait inside it.

**Reason:** the volume stays bounded and small: at most 11 lines a minute per pod, about 2.4 MB a
day at most at about 150 bytes a line, and no route line when nothing is slow. The window holds one
entry per method and declared pattern, so its size is bounded by the code (289 declared handlers),
never by the traffic. A method outside the standard ones counts as `OTHER`: the server passes any
token on, so a client could otherwise grow the window and write into the log. The pattern holds
nothing from the request, for the reasons of the entry above.

**Rejected alternatives:**
- One line per route that had a request: most lines would say nothing about the tail, for a
  volume that grows with the number of routes in use.
- All routes in one line: a long line, harder to `grep` and to sum per route.
- Percentiles per route: a histogram per route for numbers that `over_1s` and `over_3s` already
  answer; the request log's `ms=` gives exact values where needed.
- Summing the request log with `kubectl logs`: it works for what the log still holds, and needs no
  code, but the time it reaches back shrinks as traffic grows.

## A refused call names its code and its reason or scope in the request log, read from the answer itself

**Id:** af4976fc-5ed8-4d31-bcb3-b0e71c6fa14d
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** card tsk-5d8hdtqhje26, from tsk-7jhpzrvsnzm3 (2026-11-06): a project owner's joins were refused 30 times and ops could not tell which check refused them, because the line said only `403`; which answers get the tail was decided by the lead on the card's plan, 2026-11-08
**Revisit when:** the hub gets structured (JSON) logs or a log stack that indexes fields, or a `reason` or `scope` that is not a code token turns up as `?` in the log
**See:** serving.md#the-request-log-carries-ms-and-the-routes-pattern-and-one-stats-line-a-minute-says-how-loaded-the-hub-is — 8c9025ea-d9d4-449e-a343-ecd802ddbdfd — as of 2026-11-08

A 403, and any other 4xx whose `details` carry a `reason` or a `scope`, ends its request log line
in `error=<code>` with `reason=<r>` and `scope=<s>` where present (docs/api.md §1.1). A 404 or a
validation error with neither adds nothing. `middleware._noting_refusal` reads the code from the
answer's `Maity-Error` header and peeks at the envelope as it passes, at most 16 KiB and only
when the answer is not compressed. Every message goes on unchanged. Only a code token (lowercase
letters, digits, `_ . : -`, up to 64 characters) is written; anything else is `?`.

**Reason:** the line had to tell the refusing checks apart without carrying anything from the
request. A reason and a scope are the hub's own codes, but a few details elsewhere hold free
text, so the token guard keeps a future text reason out of the log. Reading the answer covers every
way a refusal is made: a raised `ApiError`, an envelope a route returns itself, and the
middleware's own refusals. Limiting the tail to 403 and to 4xx that name a reason keeps the log
as quiet as before for the common 404 and 400.

**Rejected alternatives:**
- Recording code and reason in the app's exception handlers: misses the envelopes a route returns
  without raising and the refusals the middleware answers before the app.
- `error=` on every 4xx: more noise for 404s and validation errors, whose code the status already
  says; the lead chose the narrower form.
- Logging `details` whole: `fields` and other details can name what the request sent.

## The `stats` line says how late the event loop runs and how many worker threads are busy, from a tick on the loop

**Id:** 68487d41-14dd-4fd0-8f7e-91a0a85316ff
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** card tsk-0wm9q2vxjqg3, 2026-11-01: Ops saw `GET /health` at p50 141–224 ms and p90 408–657 ms whatever the load, with at most 8 of 32 pool connections out, and could see neither the thread pool nor the event loop
**Revisit when:** the cluster gets a metrics stack, or a stall shorter than a tick has to be seen, or the hub leaves anyio's default limiter

The `stats` line ends in `loop_late_avg_ms=<n> loop_late_max_ms=<n> threads_busy_avg=<x>
threads_busy_max=<n> threads_waiting_max=<n> threads_limit=<n>`. A task on the server's event loop
(`request_stats.watch_load`) wakes ten times a second, notes how much later than asked it ran, and
reads the default thread limiter: threads taken, callers waiting, and the limit. The fields come
after the pool's, so a `grep` for those keeps working.

**Reason:** a `def` endpoint runs on a worker thread of that limiter, so a request can wait in
two places before its code runs: for the loop, and for a thread. A full pool does not explain
either, which is why these two were the missing numbers. The limiter belongs to the loop and can
only be asked from it, so the tick is a task there and not the reporter's thread; that thread
stays as the one that writes the line, so a stuck loop can still be reported. For that, the tick
overdue at that moment counts towards `loop_late_max_ms`: a loop stuck for the whole minute has
no tick left to say so. Ten looks a second cost next to nothing against the probes and requests,
and a stall under 100 ms can hide between two; those are not what is being looked for.
`threads_waiting_max` above zero says the threads ran out, which `threads_busy_max` at the limit
only suggests.

A stall across the end of a window counts in both: the line reports it as overdue, and the tick
that finally runs reports its whole length in the next window. Without a tick in a window
`loop_late_avg_ms` stays 0, so `loop_late_max_ms` is the field to alarm on.

**Rejected alternatives:**
- Timing how long each request waits for a thread: it would wrap every endpoint's hop to the
  thread, for a number the callers waiting already show.
- Percentiles of the lateness: a histogram for what average and maximum answer; the two apart say
  whether the loop is slow all the time or stalls now and then.
- The process's thread count: it holds the hub's background workers too and never shrinks with
  the load, so it does not say how many requests hold a thread.
- A `/metrics` endpoint: the reasons of the first entry above still hold.

## A request body has 120 seconds in all to arrive

**Id:** 35eb5c15-c1a3-4b16-88a5-c71aa305450f
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** the plan for card tsk-eejgfehwg4k0, approved by the team lead on 2026-11-04 (a total read deadline); the value is the implementer's; `docs/api.md` §1.3 and §1.7; implementation session, 2026-11-04
**Revisit when:** a client legitimately needs longer for a 10 MiB upload, or an ingress in front of the hub buffers whole bodies itself
**See:** attachments.md#a-large-bodys-caller-is-checked-from-its-headers-before-the-body-is-read — ea27e3d7-14b1-40ab-8158-b86ab575583e — as of 2026-11-04

Every body is read by `body.read` against one deadline, `body.BODY_SECONDS`
(120), counted from when the read starts. Its two callers are the
middleware, for every routed call, and the forge webhook (§17.4), which
reads its own body before the middleware's read. When the deadline passes,
the call is `408 request_timeout` with `Connection: close`, and what was read
is dropped. The webhook answers it alike for every slug, as it does its
other refusals.

**Reason:** a body sent slowly holds its connection and the bytes read so far
for as long as it lasts, and nothing else bounds that time: uvicorn's
keep-alive timeout applies between requests, not inside one. 120 seconds
leaves room for the largest body, a 10 MiB attachment, at about 1 Mbit/s
(about 84 seconds). The connection is closed because the rest of the body may
still be on its way.

**Rejected alternatives:**
- **A timeout per chunk:** a client that sends a little before each timeout
  ends never reaches it.
- **The deadline on attachment uploads only:** every body is read by the same
  function, and a small body needs far less than 120 seconds.

## An emergency limit on single routes comes from the environment and counts in each process; the public read limits stay, configurable

**Id:** f3198c35-b163-4fce-b3ad-683d8b825555
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** the maintainer's decision on card tsk-h238y7cpk23m and the plan the team lead approved, 2026-11-04 (confirmed: no general budget in the hub, an emergency limit per route by configuration, no runtime setting yet, the public read limits kept and configurable); reading the routes from the router rather than from the OpenAPI document came from the review of the first version, where a path converter matched one segment only (reproduced by a test, red before and green after); that `iter_route_contexts` yields the routes in the router's order is inferred from FastAPI matching with the same walk, and is checked by one test on a literal route ahead of a template
**Revisit when:** a runtime setting for route limits is built, `fastapi.routing.iter_route_contexts` changes or goes away, or the deployments' ingress limit has been tested and the public read limits are reassessed

The hub has no general request budget; the ingress holds the limit per
client. `MAITY_ROUTE_LIMITS` sets limits on single routes of the API for an
emergency, `<METHOD> <route> = <count>/<seconds>` with the route as
`/api/v1/openapi.json` lists it. When the app is built, each entry is checked
against that document, and one the document does not list with that method
stops the hub. The routes are read from the app's router with FastAPI's
public `iter_route_contexts`, which walks the included routers with their
prefixes in the order the router matches in; each is named by its path as
the document lists it and matched by the pattern compiled from its declared
path (`starlette.routing.compile_path`), so a path converter such as
`{path:path}` matches as many segments as the route serves. A request
counts against the first route whose method and pattern it fits, so a
literal route ahead of a template counts as itself. The
check runs in the middleware after the maintenance check and before the body
is read or the caller looked up. It counts per client address in the process
(`Limiter(local=True)`) and answers `rate_limited` with `Retry-After`. Without
an entry nothing is matched at all, and the OpenAPI document is not built for it.

The read limits of the public pages and the badges (60 per minute per
address) stay. `MAITY_PUBLIC_PAGE_LIMIT` and `MAITY_BADGE_LIMIT` set them as
`<count>/<seconds>`, applied with `Limiter.configure` when the app is built.
Configuring forgets only this process's counts and reads no database: the
app is built before the database may be reachable, and the counts shared
between replicas belong to the limit, not to one build of the app.

**Reason:** an emergency limit exists for the minutes a route is being
hammered, so it has to cost as little as possible: a count in the database
on every call of the route would add a write to exactly the load it is
meant to shed. Per process, several replicas each let through their own
share; for an emergency limit that is close enough, and the operator
divides by the replicas. Checking the names at startup keeps a typo from
leaving the operator believing a limit holds. The public read limits stay
because a hub run with Compose and no ingress has no other limit on them;
configurable, because 60 a minute is tight for an office behind one
address.

**Rejected alternatives:**
- **Counting in the shared counts like the other limits:** a write per
  request, see above.
- **A runtime admin setting instead of the environment:** no restart, but a
  setting, its contract and its page; left for later. A change now takes a
  restart, which is slow while the hub renders its public pages at start.
- **Matching against the templates of the OpenAPI document:** the
  document lists a converter path such as `{path:path}` as `{path}`, and a
  pattern compiled from that matches one segment, so a limit on such a route
  missed every address with a slash in it.
- **Walking the route objects of an included router directly:** this
  FastAPI keeps them in private objects (`_IncludedRouter`);
  `iter_route_contexts` is the public walk over them.
- **Counting every route whose pattern a request fits:** a literal route
  such as `/api/v1/runners/enrollments` would count against
  `/api/v1/runners/{runner_id}`.
- **Removing the public read limits now that the ingress limits every
  client:** without an ingress they are the only limit on those reads.

## Reads of the API and the dashboard's files are gzipped by the hub, not by the ingress

**Id:** 5cfd29b6-0446-4760-b602-8e854ab8937d
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** the card tsk-hn2wa8a7e2eq (the board query measured at about 2.7 MB of JSON in five pages, about 0.66 MB gzipped) and the operators' choice of the hub over the ingress, 2026-11-06
**Revisit when:** the hub serves secrets on reads, or a deployment compresses at its ingress as well

A `GET` or `HEAD` under `/api/v1/` or `/assets/` of 1024 bytes and more
is gzipped at level 6 when the request accepts it (docs/api.md §1.1); the
dashboard's own files are gzipped by `shell.AssetFiles` instead, with an
ETag per form (c6768529).
Writes are never compressed, nor anything under `/api/v1/auth/`, the
join and invitation documents a token opens (`/api/v1/join/{token}`,
`/api/v1/invitations/{token}`), an attachment's bytes, or any address
outside the two prefixes. The types that are compressed already (images,
archives, fonts, `text/event-stream`) are named in the hub, not taken
from Starlette's default, which older releases kept shorter. Starlette's
middleware compresses a body of 128 KiB and more in a worker thread.

**Reason:** the board's pages of cards are the dashboard's largest reads
and compress to about a quarter. In the hub, every deployment gets it
without a setting of its own, a self-hosted one too. Every place the hub answers a secret (a
new credential, a join line, a code, the session's CSRF token) is a write
or under `/api/v1/auth/`; the join and invitation documents under
`/api/v1/` and the pages outside the prefixes carry a token from their
own address. The first version of this list missed `/api/v1/join/{token}`,
which a review found. Leaving all of them out means no answer
carries a secret compressed together with what the request sent.
Attachments are someone's files, often compressed already, streamed with
their length against their digest. Level 6: 24.7% of the board's bytes
against 24.6% at level 9, for about a fifth less CPU. On the local hub
the event loop's lag while two clients read the board query in a loop
stayed where it was (`loop_late_max_ms` 61 to 66 with gzip, 58 to 95
without).

That the hub compresses was the operators' choice; the prefixes, the
exclusions and the level are this implementation's, not yet confirmed
by review.

**Rejected alternative:** the ingress's compression: one setting per
cluster, and none for a hub run without that ingress. Compressing every
answer: the pages and writes above. Level 9, Starlette's default: the
same size for more CPU.

## The dashboard's files are revalidated by an ETag of their content, not `no-store`

**Id:** c6768529-3654-45c7-bd5e-aab3067ce04f
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the owner's decision req-s246xb6k1mpp (option A, 2026-11-08), the card tsk-pcw785rhymyg and its plan note nte-smnd4dr3gw6y; docs/api.md §1, §16.11
**Revisit when:** a file under `/assets/` carries anything per user or private, or the shell names its files by digest (versioned names, below)

`shell.AssetFiles` answers the dashboard's files under `/assets/` (`css/`,
`js/`, `brand/`, `vendor/`) with `Cache-Control: no-cache` and a strong
`ETag`, the first 32 hex digits of the file's SHA-256, and drops
`Last-Modified`. A matching `If-None-Match` gets `304` with the same
headers. `no-cache` is on the middleware's `ROUTE_CACHE` (images.md
96d70040), so it is kept; a 404 under `/assets/` and every `/api/v1/`
answer stay `no-store`, the shell keeps its own `no-cache`, and
`/assets/landing/` its own rule.

Each encoding is a representation with its own strong tag. A file of
1024 bytes and more whose type is not compressed already has a gzip form,
made by `AssetFiles` itself at the middleware's level 6 and with no time
in its header, tagged `"<digest>-gzip"`; a request that accepts gzip gets
it with `Content-Encoding: gzip`. Such a file's answers, the `304`s
included, say `Vary: Accept-Encoding`. The compression middleware leaves
these four directories alone (`compression.OWN_ENCODING`); it still
compresses the rest of `/assets/` and `/api/v1/` as 5cfd29b6 says. A
`Range` on the stored form is honoured with an `If-Range` that names its
ETag; a date or another tag gets the whole file. The gzip form is sent
whole. The file is read, hashed and gzipped in `lookup_path`, which
Starlette runs in a worker thread, and kept per process for its path
while its change time and size stay the same.

**Reason:** the owner decided it (req-s246xb6k1mpp, option A: "the
dashboard's static files may be cached"): the files hold no private
data, and every reload fetched all 97 of them, 691 KB gzipped
(tsk-fxjtwmkc4md5). `no-cache` makes a browser ask again on every use,
so a deploy reaches it at once: a changed file has a new ETag and comes
back `200`; two pods with different files during a rolling update give
different ETags, also `200`. Only the ETag decides, so `If-Modified-Since`
alone never answers `304`, and a date `If-Range` never selects a range:
Starlette compares it with `Last-Modified`, which these answers do not
have, so `AssetFileResponse` compares the ETag alone.

**Rejected alternatives:**
- Starlette's own ETag (an MD5 of the change time and size): an image
  built with normalised file times could keep the old ETag for a changed
  file of the same size, and a browser would keep the old file.
- The middleware's gzip with the stored file's tag (the first version of
  this PR): two different bodies under one strong ETag, and its `304`
  went out before the middleware could add `Vary` (review of #1518,
  RFC 9110 §8.8.3.3, §15.4.5).
- A weak ETag for both forms: the contract (§16.11) promises a strong
  one, and a weak tag can never select a range.
- Versioned names with a long `max-age` (`?v=<digest>`, `immutable`, as
  `/assets/landing/` does): a reload would send no requests at all, but
  the shell's 93 `<script src>` and 2 `<link href>` would need a rewrite
  in `shell_document`, the `url()` references inside the CSS would stay
  `no-cache` anyway, and it is a contract change of its own. A
  follow-up once this card's numbers are measured.

## The shell names the dashboard's files by version, and that request is cached for good

**Id:** d427747e-e7f1-4226-a624-5284f8d61103
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the card tsk-0pp41wxp6f75, its plan notes nte-8d01b7h5b0cf and nte-46bhk8n4nrmd (approved by lotse#wtwy, seq 96636), within the owner's caching decision req-s246xb6k1mpp (option A); docs/api.md §1, §16.11
**Revisit when:** a dashboard file is loaded by a name the shell neither writes nor lists, a file under `/assets/` carries anything per user, or the dashboard gets a build step that names its files itself

c6768529 left one revalidation per file: after #1518, a warm load of a signed-in page still asked about 100 times and got `304` 98 times out of 102 (maity-ops-team#q8q9's measurement on prod, seq 96553). This record names the files so that a warm load does not ask at all. Its "Revisit when: the shell names its files by digest" has come, and the versioned names it rejected are now built. Everything else in c6768529 stays: the ETag, the gzip form and the `no-cache` answer for any other request.

- `shell.versioned` adds `?v=<version>` to every `src`/`href` of the shell that names a file under `brand/`, `css/`, `js/` or `vendor/`. The version is the first 16 hex digits of the SHA-256 of the body sent, the same form `/assets/landing/` uses.
- A stylesheet is served with its `url()`s to such files (fonts, brand masks) versioned the same way, so its version is that of the rewritten body. It is sent from memory and whole, as the gzip form is.
- The files a script loads later by a name it builds (i18n catalogs, Keep the Why's files, brand pictures) are listed in `<script type="application/json" id="maity-assets">`. `web/js/assets.js` (`M.assetQuery`) reads that block.
- `AssetFiles` answers `public, max-age=31536000, immutable` only when the request's one `v` equals the version of the body this hub would send. Any other request gets c6768529's answer.
- The middleware lets those four directories choose it (`DASHBOARD_FILES`), as it lets `/assets/landing/`.

**Reason:**
- A deploy changes the shell, which is `no-cache`, and with it the name of every file that changed. So a browser can keep the others without asking.
- The version is compared with the body itself, never taken on trust from the request. So during a rolling update (helm `maxSurge 1`, `maxUnavailable 0`), a shell from one pod asking another pod for a version it does not have gets that pod's file `no-cache`, and is never pinned under the wrong name. The same holds for a stale link, or a file changed on a running hub.
- A load that crosses the two pods may run old and new files together once, as it could before; the next use revalidates.
- A query instead of a new file name leaves every relative URL as it is: `i18n.js` builds `i18n/<tag>.js` from its own address. Fixture mode (`file://`) keeps the plain names, and no build step is needed.
- The data block is not run, so the shell's CSP (`default-src 'self'`) stays as it is.

**Rejected alternatives:**
- File names with the digest (`app.<hash>.js`): every relative name a script builds, and fixture mode, would need a mapping, and the files on disk would have to be copied or renamed.
- `404` for a version this hub does not have: a page from the other pod would lose that script outright instead of running the file this pod has.
- Session affinity during a deploy, to keep a browser on one pod: an ingress setting for a once-per-deploy case that `no-cache` already covers.
- Taking the version from the request without comparing it with the body: a stale or foreign version would be cached for good with the wrong file.
