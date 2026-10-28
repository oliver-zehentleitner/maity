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

## The badge template ships with the hub, and only the badge and the public swarm page may choose public caching

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
only for a successful GET of `/badge/{slug}.svg` or of the public swarm page
`/api/v1/swarm/{slug}` (§6.22, its list in `middleware.PUBLIC_PATHS`),
including a 304; a missing, closed or opted-out one stays `no-store` and never
validates an old ETag.

**Reason:** relying on a dashboard file would make the public endpoint fail in
an API-only installation. Packaging both templates preserves that behavior without a dashboard dependency.
A global public-cache allowance would let an unrelated
route cache private content by choosing that header. The approved badge and the
opted-in swarm page are the specific exceptions, not a change to the hub's
ordinary cache policy.

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
path cannot ask for the other path's. The root's `X-Robots-Tag: noindex` while the landing
page is not enabled is added by the middleware too, on `GET` and `HEAD` of `/` only, because
the root is a static file the dashboard mount serves and no route of the hub; the setting
is read per request, and an unreadable setting counts as off. The join host answers both
files `not_found`, in `join_host.route`, before its redirect.

**Reason:** the dashboard's mount would otherwise answer `/robots.txt` from the web
directory (or with its 404), and the root's header must follow a setting an admin changes
without a restart.

**Rejected alternatives:**
- Static files in the web directory: they would not follow the landing setting or
  `MAITY_PUBLIC_URL`.
- A `noindex` meta tag in `index.html`: the dashboard's page is also the signed-in page, and
  a header is what a crawler reads without rendering.
