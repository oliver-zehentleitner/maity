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

Measured on maity.team on 2026-10-25, after the stopping hub released its
long-polls (#332): the upgrade's 503 window is at most 12.6 s, against
69 s before; what remains is mostly the new hub's own start (about 5 s),
so the gap Recreate costs stays a few seconds.

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

## The Ingress is a plain networking.k8s.io/v1 Ingress; ingress-nginx annotations are only defaults

**Id:** adc362f5-08ef-41e0-ab34-05f07cd5fa26
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** implementation session, 2026-10-22 (the Helm chart's review)
**Revisit when:** the maintainer's cluster moves to a controller that serves only Gateway API, or a second controller's annotations become defaults

The chart's Ingress is a plain `networking.k8s.io/v1` object that any
controller serves through `ingress.className`. Its default annotations
carry the long-poll settings for ingress-nginx: 75 s read and send
timeouts, buffering off. They merge with the operator's annotations and can
each be set to null. The chart README says that upstream ingress-nginx has
been retired since March 2026, with no further releases or security fixes,
and that a new cluster should use a maintained controller with its own
equivalents of the three settings.

**Reason:** the hub needs only what every Ingress controller offers, plus
two properties of the long-poll: at least 55 s per request, and an
unbuffered response. Naming one controller's settings as defaults gives
the common case a working install. A plain Ingress keeps every controller
open, including the one the maintainer's cluster runs.

**Rejected alternatives:**
- A Gateway API `HTTPRoute` instead of the Ingress: the direction of the
  ecosystem, but not every cluster has the Gateway CRDs, and the
  long-poll timeouts are policy attachments that differ per
  implementation. It is the revisit, not the default.
- No default annotations at all: neutral, but every ingress-nginx install
  would buffer the long-poll and cut it at 60 s until someone notices.

## A hub serves only on its own schema head; rollback is not a downgrade

**Id:** cc9f37de-1684-41f1-b090-a2dc344a3673
**Type:** constraint
**Status:** active
**Evidence:** inferred
**Source:** implementation session, 2026-10-22 (the Helm chart's review)
**See:** persistence.md — ce7a3627-d04d-4708-bac9-ed0c7d64cfe4 — as of 2026-10-22
**See:** kubernetes.md — eced7109-a606-4549-b2f2-962e7436f8a8 — as of 2026-10-22
**Revisit when:** a migration has to run while the old version keeps serving (expand/contract migrations), or `maity-hub` gets a downgrade command

A hub process serves only when the database is at exactly the migration
head of its own version. There are three consequences on Kubernetes.
- **During an upgrade:** once the hook Job has migrated, the old pod's
  readiness fails with `schema_outdated`, so an upgrade with a migration
  is unavailable for the migration plus the new pod's start.
- **Rollback:** `helm rollback` runs no migration (the hook is
  `pre-install,pre-upgrade` only) and `maity-hub` has no downgrade
  command, so a rollback to a version with an older schema head starts a
  hub that refuses to serve and crash-loops. The chart README says to
  roll back only to a version with the same schema head and otherwise to
  fix forward.
- **Helm's timeout:** the Job's deadline (300 s by default) stays under
  the `--timeout` the README's commands pass (10 m), so a Job that
  outlived Helm cannot still migrate under the old pod after Helm
  reported the failure.

**Reason:** this follows from serving only on the current schema
(persistence.md). Writing it down here keeps the upgrade and rollback
instructions honest about what Helm can and cannot undo.

**Alternatives:** none were in contention for this chart. Expand/contract
migrations, where old and new versions both run on the new schema, would
lift the rule. They are the revisit, not something V1 needs with one pod.

## A stopping hub answers its open long-polls at once and bounds the graceful shutdown

**Id:** 3194a790-29c5-43b6-a07a-cdb21f2f6aae
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** the measurement of the upgrade on maity.team (events of 2026-10-25 06:35–06:36 UTC) and a local stop test, card tsk-4tad7bmbkzh2, agreed with the coordinator (seq 3405)
**Revisit when:** the chart moves away from Recreate, or an upgrade's 503 window grows again
**See:** kubernetes.md#one-pod-replaced-with-recreate-no-replica-count-in-the-chart — 5e42eb26-9883-49e2-89c0-9fe4e6517c62 — as of 2026-10-25

`maity-hub serve` runs uvicorn through a server whose stop handler hands
`longpoll.begin_shutdown` to the event loop (`call_soon_threadsafe`),
which sets `longpoll.stopping` and wakes every waiter. The handler itself
takes no lock: a signal can interrupt code that holds the registry's
lock, and a handler waiting for that lock would never return (found in
review). An events or runner
long-poll then answers at once with what it has, empty and not
superseded, as if its wait had ended. Uvicorn's
`timeout_graceful_shutdown` (10 seconds) bounds any other request still
running.

**Reason:** an upgrade of maity.team was measured at about 43 seconds
of 503. Four of them came from the migration (the old pod's `/health`
answers 503 once the schema moved past it), about 32 from the old pod
stopping, and about 7 from the new pod starting. The image was already
on the node, pulled by the migrate hook. The old pod waited for its open
long-polls (up to 55 seconds each) because uvicorn waits for every open
connection unless told otherwise. Locally, with one long-poll open, a
stop took 49 seconds before and 0.2 after. Clients wait again after an
empty answer anyway (§8.3).

**Rejected alternatives:**
- `RollingUpdate` with `maxSurge: 1`: no gap, but two processes overlap
  (the entry above).
- Only a short `timeout_graceful_shutdown`: the long-polls would be cut
  off mid-request instead of answering.
- Pre-pulling the image before the rollout: the migrate hook already
  pulls the same image, so there was nothing to gain.

## An upgrade with a migration stops the hub first

**Id:** d295eb2a-38ad-4e27-9dfa-524bb0963a24
**Type:** decision
**Type:** incident
**Status:** active
**Evidence:** confirmed
**Source:** the deploy of 2026-10-28 (migration 0060 failed four times with a deadlock against the serving hub); card tsk-q6t6st3hnhcc
**Revisit when:** migrations take their locks in a fixed order with a lock timeout and retry, or the chart can stop the hub itself
**See:** kubernetes.md#migrations-as-a-pre-installpre-upgrade-hook-job-not-an-init-container — eced7109-a606-4549-b2f2-962e7436f8a8 — as of 2026-10-28

`deploy/scripts/helm-upgrade.sh` scales the hub to 0, runs `helm upgrade` (the hook Job migrates alone) and
scales back to the replicas it had on any exit. A release whose migration touches no busy table may use
plain `helm upgrade`. A migration that alters `project`, `human`, `membership` or another table every
request reads or writes is written to run with the hub stopped, and the release notes say so.

**Reason:** the hook Job runs while the old pod still serves. Migration 0060 altered several busy tables,
deadlocked against the old pod's open transactions on PostgreSQL, and the Job failed on all four attempts;
the same upgrade went through once the hub was stopped. The old pod answers 503 `schema_outdated` as soon
as the schema has moved, so stopping it first adds almost no downtime.

**Rejected alternatives:**
- A `lock_timeout` and a retry in the migration alone: it turns a hang into a failure, but while the hub
  keeps its transactions open the same conflict comes back on every retry.
- Moving the migration into an init container: with `Recreate` the old pod is gone by then, but it
  migrates on every pod start and makes a failed migration an outage (the first entry above).
- A chart hook that scales the Deployment itself: it needs RBAC in the chart and a second hook to restore
  the replicas, and a failure between the two would leave the hub at 0; a script with a trap keeps that
  restore in one place.


## Mail: the signing key and the SMTP password come from Secrets by reference, the rest are plain values

**Id:** f1c9c8ad-96ad-408d-b536-fdf027c5fe35
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** the card that put mail live on maity.team (SMTP account, signing key, test send), 2026-10-29, and its review, which found the chart without mail values; docs/api.md §16.2 (the environment wins over the admin settings)
**Revisit when:** the admin settings can store the SMTP password and signing key themselves for a Kubernetes install, or the chart gets more mail values

The chart takes `mail.signingKeySecret` (`MAITY_MAIL_SIGNING_KEY`) and `mail.passwordSecret` (`MAITY_SMTP_PASSWORD`) as names of
existing Secrets, like the database URL and the forge token, and `mail.host`, `port`, `tls`, `username`, `from`, `replyTo` as plain
values. Nothing is rendered without a value, so a release without mail is unchanged. Mail on maity.team went live first as a
config-only Helm revision with the same variables in `extraEnv`; this wires them into the chart so that a `helm upgrade` with the
chart's own values cannot drop them. The rendered environment of the live values is the same before and after moving them.

**Reason:** the signing key and the password are secrets and stay out of values files; the host, port, TLS mode and addresses are not,
and are easier to review as values. The reply-to address differs from the sender on purpose: the sending account is a no-reply
account, and replies should reach a mailbox that is read (the addresses are the operator's choice, the chart has no default). SPF,
DKIM and DMARC are records at the domain's DNS and not part of the chart or the cluster; they stay with the person who owns the DNS,
and whether they are set decides whether mail arrives, which the test send shows.

**Rejected alternatives:**
- Everything through `extraEnv`: it works and carried the first deployment, but a release that forgets the entries sends no mail
  and nothing says so; the chart already knows the other two secrets by name.
- The password as a chart value: it would sit in a values file and in the release history.
- The chart change before the deployment: mail was needed live first, and the chart change needs a review and a deploy of its own.

