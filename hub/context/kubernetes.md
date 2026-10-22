# Kubernetes

## One pod, replaced with Recreate; no replica count in the chart

**Id:** 5e42eb26-9883-49e2-89c0-9fe4e6517c62
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** implementation session, 2026-10-22 (the Helm chart)
**See:** events.md — 6310ef59-6010-4fa5-95d5-30f20bc00117 — as of 2026-10-22
**See:** https://github.com/oliver-zehentleitner/maity — 4713ab88-72a2-408b-9625-87345628eb5a — as of 2026-10-22
**Revisit when:** the long-poll ownership, the nonce window and the probe sweep move to the database, so that a second process is safe

The chart (`deploy/helm/maity-hub`) runs exactly one hub pod with the
`Recreate` strategy: on an upgrade the old pod stops before the new one
starts. `replicas` is fixed in the template, not a value, and the values
schema refuses unknown keys, so `replicaCount: 2` fails at install time
instead of starting a second process.

**Reason:** the long-poll notifier, "one long-poll per session", the
request-signing nonce window, the login and join rate limits and the probe
worker all live in the process (docs/architecture.md §8). Two pods at once,
even for the seconds of a rolling update, would let a signed request be
replayed against the other pod and split the limits. An upgrade costs a few
seconds without a hub; clients already re-poll and retry.

**Rejected alternatives:**
- `RollingUpdate` (the Deployment default, also with `maxSurge: 1`):
  no gap during an upgrade, but the old and the new pod overlap.
- A `replicaCount` value defaulting to 1: the usual chart shape, but it
  offers a setting the hub does not support yet.

## Migrations as a pre-install/pre-upgrade hook Job, not an init container

**Id:** eced7109-a606-4549-b2f2-962e7436f8a8
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** implementation session, 2026-10-22 (the Helm chart)
**See:** persistence.md — ce7a3627-d04d-4708-bac9-ed0c7d64cfe4 — as of 2026-10-22
**See:** kubernetes.md — 5e42eb26-9883-49e2-89c0-9fe4e6517c62 — as of 2026-10-22
**Revisit when:** the chart is deployed by a tool that does not run Helm hooks

`maity-hub migrate` runs as a Job with the Helm hook
`pre-install,pre-upgrade`, before the Deployment is changed. A failing Job
fails the install or upgrade and leaves the Deployment as it was. The Job
stays after it succeeds, until the next upgrade replaces it, so its log can
still be read. `migrate.enabled: false` leaves the migration to the operator.

**Reason:** with `Recreate` the old pod is already gone when a new pod's
init container would run, so a failed migration in an init container means
no hub until someone intervenes. A hook Job fails while the old hub still
serves. It also runs once per release, not on every pod restart or
reschedule.

**Rejected alternatives:**
- An init container running `maity-hub migrate`: no Helm hooks needed, but
  it migrates on every pod start and turns a failed migration into an
  outage.
- Migrating only by hand: it stays possible through `migrate.enabled`, but
  as the default every upgrade would need a step outside Helm.

## Readiness on /api/v1/health, liveness on /api/v1/help

**Id:** c391bbda-dd25-4fc3-8284-db5438f788f0
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** implementation session, 2026-10-22 (the Helm chart)
**Revisit when:** the hub gets an endpoint meant for liveness

Readiness and `helm test` use `/api/v1/health`, which answers 503 while the
database is unreachable or not at the migration head. Liveness and startup
use `/api/v1/help`, which answers from the process alone.

**Reason:** a database outage should take the pod out of the Service, not
restart it. A restart cannot fix the database, and it drops every open
long-poll. An endpoint without the database still shows whether the event
loop answers, which a TCP check would not.

**Rejected alternatives:**
- `/api/v1/health` for liveness too: restarts the hub in a loop for as long
  as the database is down.
- A TCP socket check for liveness: passes even when the event loop no
  longer answers.
