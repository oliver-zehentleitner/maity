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
**Status:** active
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
**Status:** active
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

Each request is logged as `METHOD path status ms=<n> route=<pattern>` (`middleware._access`): how
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

