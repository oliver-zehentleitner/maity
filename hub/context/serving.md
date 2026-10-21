# Serving

## The dashboard is optional for the hub, unless it was configured explicitly

**Id:** 1d9642af-0ef2-48b3-98a7-63925936e150
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** implementation session, 2026-10-21

The hub mounts the static dashboard at `/` after the API routes, from
`MAITY_WEB_DIR` or, unset, from `web/` beside `hub/` in the checkout.
An explicitly set `MAITY_WEB_DIR` that is not a directory stops the hub
at startup. A missing default directory only logs a warning, and the hub
serves the API alone. The image copies `web/` when the build context has
one and leaves `/app/web` empty otherwise. The mount never serves a path
with a segment starting with `.` and nothing under `/api`, and the image
build leaves dotfiles and `node_modules` out.

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
