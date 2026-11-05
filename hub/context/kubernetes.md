# Kubernetes

## One pod, replaced with Recreate; no replica count in the chart

**Id:** 5e42eb26-9883-49e2-89c0-9fe4e6517c62
**Type:** decision
**Status:** superseded
**Superseded by:** ec91fe03-1e12-4fb6-8c8e-f09ae8528e5d
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
timeouts, buffering off; and, since a later change (5eb8e035, this file),
the body size an attachment upload needs. They merge with the operator's annotations and can
each be set to null. The chart README says that upstream ingress-nginx has
been retired since March 2026, with no further releases or security fixes,
and that a new cluster should use a maintained controller with its own
equivalents of these settings.

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
**Status:** needs-review
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

`deploy/scripts/helm-upgrade.sh` scales the hub to 0 and runs `helm upgrade` (the hook Job migrates alone).
Once Helm succeeded the hub runs the replicas the release renders (Helm resets the scaled Deployment to
the chart's value, and a changed `replicas` must not be undone), also when the rollout check after it
fails; when the script ends before Helm or Helm fails, it scales back to the replicas it had. A hub
found at 0 stays at 0. A release whose migration touches no busy table may use
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
chart's own values cannot drop them. The rendered environment of the live values is the same before and after moving them. Moving the live values from `extraEnv` into
`mail.*` drops them from `extraEnv` in the same revision: the chart renders both, so the names would appear twice in the container
env and the later (`extraEnv`) one wins, which hides whether the chart values are in effect. With a host set, port and TLS always
come from the chart (its defaults included) and win over the admin settings; an operator who wants those in the admin UI sets no host.

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


## The instance key is a chart value too: secretKey.existingSecret

**Id:** dbeb3ff3-a9a8-480b-92e8-13fcaa41b8f9
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** the coordinating agent's decision after the review of the mail wiring, 2026-10-29 (the contract promised it; the chart README sent it through `extraEnv`); hub/context/persistence.md and notifications.md for what the key seals
**See:** kubernetes.md#mail-the-signing-key-and-the-smtp-password-come-from-secrets-by-reference-the-rest-are-plain-values — f1c9c8ad-96ad-408d-b536-fdf027c5fe35 — as of 2026-10-29
**Revisit when:** the hub can rotate the key, or another secret joins the chart's list

`secretKey.existingSecret` (and `key`, default `secret-key`) names the Secret holding `MAITY_SECRET_KEY`, rendered into the hub and the
migrate Job like the database URL. Without a value nothing is rendered. A release that moves the key from `extraEnv` into it drops it
from `extraEnv` in the same upgrade; the chart does not deduplicate and the later entry wins. The default key name `secret-key` follows the
chart's other Secrets (`database-url`, `github-token`, `mail-signing-key`). A Secret created with the first README holds the key as
`MAITY_SECRET_KEY`; such a release sets `secretKey.key: MAITY_SECRET_KEY` when it moves, otherwise the `secretKeyRef` names a missing key
and the migrate Job and the hub do not start (loud, nothing is lost).

**Reason:** the key seals what the hub stores at rest (forge webhook secrets, a stored SMTP password, second-factor secrets) and is
the root of derived keys (notification positions use HKDF of it). A release that loses it, as one with the chart's own values would
while the key lives only in `extraEnv`, leaves all of that unreadable, and a new key does not bring it back: the loss is worse than
that of the mail settings and cannot be repaired by setting the variable again.

**Rejected alternatives:**
- Keeping it in `extraEnv`, as the first chart README did: it works while every upgrade carries the entry and fails silently when one
  does not.
- Making it a required value: an install without webhooks or stored passwords does not need it, and the features that do refuse
  loudly (`secret_key_missing`).


## Attachments on the k3s setup: a volume the chart mounts, and a tar in the same backup run

**Id:** 9111cb2f-89b0-4088-8c92-2fa5c1348ec7
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** the maintainer's request to switch attachments on in production, as passed on by the coordinating agent (2026-10-29), docs/api.md §8.7 and hub/README.md (`MAITY_ATTACHMENT_DIR`), the store's code (`attachment_store.py`: project directories 0700, files written whole)
**See:** kubernetes.md#mail-the-signing-key-and-the-smtp-password-come-from-secrets-by-reference-the-rest-are-plain-values — f1c9c8ad-96ad-408d-b536-fdf027c5fe35 — as of 2026-10-29
**Revisit when:** the store moves to an object store (`s3`), or fourteen tars and dumps no longer fit comfortably on the node's disk (the volume holds more than a few GiB)

`deploy/k3s-single/attachments.yaml` is a 10 GiB claim, `maity-attachments`. The chart takes it as `attachments.existingClaim` (with `mountPath` and
an optional `quotaBytes`), mounts it into the hub and sets `MAITY_ATTACHMENT_DIR`, because the hub checks the directory at every
start. The quota stays at the hub's default of 1 GiB per project.

The files are not in the database, so the nightly backup takes them along: an init container of the backup Job, running as the hub's user (10001), tars
the volume into `maity-<time stamp>.attachments.tar` and hands the time stamp to the dump container, which writes `maity-<time stamp>.dump`, rotates
both together and ends with `dump ok: <dump> <bytes> attachments <bytes>`. With `DUMP_REQUIRES_ATTACHMENTS=1` (set when the release has the claim) `helm-upgrade.sh` also demands the tar in that line; a tar that
fails, is missing or has 0 bytes stops the dump Job, so there is no mark (a tar of an empty directory is about 10 KiB and passes: the check is
that the tar was written, not that there are files). This holds only once the new `backup.yaml` is applied: an old CronJob writes the old mark
without the tar, so for the release with attachments the order is `attachments.yaml`, `backup.yaml`, probe dump, then the upgrade. `restore-attachments.yaml` puts one night's files back and replaces the volume's contents.

**Reason:** the hub creates the project directories with mode 0700 under its own user, which the dump's user (999) cannot enter; a second container of the
hub's user is the way to read them without changing the hub or the ownership of the dumps. One run, one time stamp and one marker mean that a dump and
the files of the same night belong together and that "the dump is ok" cannot be true with the files missing, which a restore without them would hide
(messages that name files that are not there). `tar` exits 1 when a file changed or vanished while it was read (an upload that finished meanwhile);
that is tolerated, any other exit fails the Job. The volume is on the node's disk like the database and the backups: copying the backups off the host
stays necessary. Its size is not enforced either (local-path): fourteen nights keep fourteen tars, so the room is `14 × (the volume's size + a dump)`
against the node's free disk, which the init container checks before it writes (it needs twice the volume's size plus 1 GiB free). Today the
database is under 100 MB and the node has about 50 GB free; the backup claim's 5 GiB cannot be raised on local-path, and compressing would cost CPU for
files that are mostly compressed already.

The restore extracts with `--strip-components=1`: the tar's first entry, `./`, is the root of the volume, which belongs to the provisioner (root, 0777)
and not to the restoring user, so tar's attempt to set its time and mode failed with exit 2 after the files were back. A cut-off tar is found by
listing it before the volume is emptied.

Changed on 2026-11-04: the files are now encrypted, `maity-<time stamp>.dump.gpg` and `.attachments.tar.gpg`, and the restore streams the tar,
decrypted and listed off the instance, into a Job that waits for it ("The k3s backups are encrypted with gpg", below). The `dump ok:` line keeps
its shape, with the encrypted sizes first, so `helm-upgrade.sh` reads it as before.

Changed on 2026-11-01: the migrate Job used to mount the claim too, only because it shares the hub's environment and `MAITY_ATTACHMENT_DIR` must name a
writable directory. No migration reads the store. On a two-node cluster the Job landed on the other node than the running hub, the `ReadWriteOnce` claim
gave a Multi-Attach error and the upgrade ran into its deadline, so the Job now has neither the variable nor the mount. A wrong directory is now found
when the hub starts, after the migration, not before it, and the hub is down until it is fixed (`Recreate`: the old pod is already gone). The way back is another `helm upgrade` with the same image and the fixed value; `helm rollback` only helps if the upgrade did not move the schema, otherwise the old image needs the dump restored (no downgrade, see "A hub serves only on its own schema head"). A rare setting that fails loudly was weighed against a blocked upgrade on every second node. `extraVolumes` still reach the Job: a `ReadWriteOnce` claim there has the same problem.

**Rejected alternatives:**
- Relying on the hub being scaled to 0 first: `helm-upgrade.sh` does that, against migration deadlocks, but a plain `helm upgrade` would still block, for a mount nothing reads.
- Affinity of the Job to the hub's node: the Job would keep a volume it has no use for, and stay pending when that node has no room.
- `extraVolumes`, `extraVolumeMounts` and `extraEnv` in the values file: it works, and it is how a release forgets the volume at the next upgrade
  with other values; the files would then be orphaned and every attachment call would answer `attachments_not_configured`.
- A second CronJob for the files: two time stamps, and no single marker for "the backup is complete".
- Running the whole backup as the hub's user: it would change who owns the dumps and run `pg_dump` as a user the database setup does not know.
- Opening up the hub's file modes for the group (a change in the hub for the backup's sake): the 0700 directories are deliberate.
- Compressing the tar (`gzip`, which the postgres image has): attachments are mostly formats that are compressed already (images, PDFs, archives), so
  it saves little, costs CPU on the node that also runs PostgreSQL and the hub, and changes the file name, the restore (`tar -z`) and every script that reads
  the mark. The coordinating agent first asked for it and agreed to drop it for these reasons (2026-10-29).
- Making the backup claim bigger: local-path cannot expand a bound claim (the apply of the manifest would fail) and does not enforce the 5 GiB anyway;
  the node's disk is the limit, so the init container checks the room before it writes.
- Backing up only when the volume changed: a cheap saving on a small volume, and a night without a tar breaks the "same time stamp" rule.

## The k3s backups are encrypted with gpg to a public key in a Secret, and the Job fails without it

**Id:** f6cd5dc1-f718-4490-92fc-285f88085514
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** hardening card tsk-ngx42j6r0jke (the maintainer, 2026-11-04); the tool and the failure rule chosen by the team lead on the plan, 2026-11-04; `deploy/k3s-single/backup.yaml`, `deploy/k3s-single/restore-attachments.yaml`, docs/install/README.md
**See:** kubernetes.md#attachments-on-the-k3s-setup-a-volume-the-chart-mounts-and-a-tar-in-the-same-backup-run — 9111cb2f-89b0-4088-8c92-2fa5c1348ec7 — as of 2026-11-04
**Revisit when:** the postgres image stops shipping gnupg, the backups move to an object store with its own encryption, or `age` ships in an image the setup already trusts

Both containers of the backup Job pipe their output (`pg_dump -Fc`, the
tar of the attachment volume) through `gpg --encrypt --recipient-file`
under `umask 077`, so the night's files are `maity-<ts>.dump.gpg` and
`maity-<ts>.attachments.tar.gpg`, mode 0600, and nothing unencrypted
reaches the disk. The public key comes from the Secret
`maity-backup-key` (`backup.pub`), mounted as optional. The init
container checks it first: missing, a private key, or no public key
ends the Job as failed with a `backup failed:` line, before anything
is written. A restore decrypts where the private key is: the dump is
decrypted to a file there and read whole with `pg_restore -f /dev/null`
before it goes to `pg_restore --clean` over `kubectl exec` (a listing reads
only the start and passes a cut-off dump), and the tar is checked to
read without an error and to reach its end-of-archive block (`tar -tR`
with GNU tar, its listing written to a file since `sh` has no
`pipefail`; a plain listing passes a tar cut off between two files)
and streamed with its SHA-256
into a restore Job that waits for it. Both run as one block each that
stops before the cluster when the decryption or the check of the file
fails. The Job keeps the stream in a scratch volume and empties the
attachment volume only when what arrived has that digest, so a wrong
key, a backup cut off or a stream cut off on the way leaves the files
in place. Backups written before encryption
are left alone and counted in every night's log.

**Reason:** a backup holds the verifiers of every agent credential, and
it sits on the node next to the database and is copied elsewhere. With
the private key off the cluster, neither the node's disk nor a copy
can be read. gpg is already in the pinned `postgres:17.10` image, so no
other image enters the backup path. A backup must never stop silently:
a volume for a missing Secret would leave the pod waiting with no
failed Job, so the volume is optional and the script refuses instead.
`dd` counts the bytes before encryption, since an encrypted empty
stream is not empty. The shell has no `pipefail`, so a failure before
gpg leaves a mark the script checks.

**Rejected alternatives:**
- `age`: not in the postgres image, and there is no official image of
  it. A second step would bring in a third-party image or an install
  at run time.
- A symmetric key or passphrase in a Secret: the key to read the
  backups would then be on the node they protect against.
- Deleting the old unencrypted backups automatically: it removes what
  might be the only copy of a night. The operator deletes them after
  copying them off.
- A restore Job that reads the private key from a temporary Secret:
  simpler to run, but it puts the private key on the cluster.
- Checking only the tar's first header in the Job before emptying the
  volume: a tar or stream cut off between two files still unpacks
  without an error, so the volume ends up with part of the files.
- Staging the stream in the attachment volume itself: the volume
  would need room for its contents twice; the scratch volume uses the
  node's disk once.

## The ingress lets a 10 MiB upload through: 11m for ingress-nginx, a buffered route of its own on Traefik

**Id:** 5eb8e035-d2f3-4eed-872b-7e21bd473792
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** the plan for card tsk-eejgfehwg4k0, approved by the team lead on 2026-11-04; ingress-nginx's documented default `proxy-body-size` of 1m and Traefik's documented buffering middleware (not reproduced on a cluster); `docs/api.md` §8.7; implementation session, 2026-11-04
**Revisit when:** the hub's attachment cap changes, Traefik can buffer a request without its response (a `disableResponseBuffer` option in a release k3s ships), or the k3s setup moves off Traefik
**See:** kubernetes.md#the-ingress-is-a-plain-networkingk8siov1-ingress-ingress-nginx-annotations-are-only-defaults — adc362f5-08ef-41e0-ab34-05f07cd5fa26 — as of 2026-11-04

The chart's default annotations gain
`nginx.ingress.kubernetes.io/proxy-body-size: "11m"` for the whole host, and
`deploy/helm/check.sh` checks that the value stays above the hub's
`ATTACHMENT_CAP`. The k3s setup sets that key to null and applies
`deploy/k3s-single/uploads.yaml`: a Traefik `IngressRoute` that matches only
`POST …/attachments`, with a `buffering` middleware of at most 11 MiB.

**Reason:** the hub takes a 10 MiB attachment (§8.7), but ingress-nginx
refuses a body over 1 MiB by default, so an upload between the two caps
fails at the ingress. 11 MiB leaves room above the hub's cap: a file just
over it, up to 11 MiB, gets the hub's own `payload_too_large`, and a larger
one the ingress's own 413. The hub caps every other body itself, at 1 MiB at
most: 64 KiB by default, 512 KiB for the landing, legal, sign-in and sign-up
pages' settings and their previews, 1 MiB for an image upload (logo, banner,
avatar) and for a forge webhook delivery. A host-wide limit therefore needs
no finer split. Traefik has no body limit by default, so on k3s an upload
would pass without the route too. The route is there to bound the upload at
the edge as ingress-nginx's value does, and to have Traefik take the whole
body, on disk past 1 MiB, before it passes the request on: a slow upload
then waits at Traefik, and reaches the hub whole and at once.

**Rejected alternatives:**
- **One buffering middleware for the whole host on Traefik:** Traefik's
  buffering holds back the response as well, and the event long-poll's answer
  must reach the client unbuffered (§8); the option to buffer only the
  request is not in a release k3s ships.
- **A separate Ingress with its own `proxy-body-size` for the upload path in
  the chart:** an Ingress path cannot match the method or the
  `{owner}/{slug}` segments without regex annotations, and the hub already
  caps the other bodies, so a second Ingress object adds nothing over one
  host-wide value.
- **A 2m host-wide limit plus 11m for the upload path:** the same second
  object for limits the hub already enforces itself.

## The general request limit is the ingress's: one per client address, off until every agent's `maity wait` retries a 429

**Id:** a4438713-f4a6-47da-ae40-1d580e68126f
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** the maintainer's decision on card tsk-h238y7cpk23m and the plan the team lead approved, 2026-11-04 (the decision and the values are confirmed); Traefik's source (v3.3, `rate_limiter.go`, oxy `connlimit`) for the 429 and its `Retry-After`; ingress-nginx's documentation for its 503 default and its count per controller replica; the count per Traefik router, the count per spelling of the host and the cap's place after the buffering were reproduced in review on a local Traefik v3.3.7, not on a cluster
**Revisit when:** a CLI release whose `maity wait` retries a 429 is installed on every agent (then the limit can be on by default), the chart ships a Gateway API route, the k3s setup moves off Traefik or runs more than one Traefik, or the hub's attachment cap or memory limit changes
**See:** kubernetes.md#the-ingress-lets-a-10-mib-upload-through-11m-for-ingress-nginx-a-buffered-route-of-its-own-on-traefik — 5eb8e035-d2f3-4eed-872b-7e21bd473792 — as of 2026-11-04

The hub has no general request budget. Its own limits are per route,
among them sign-ins, codes, sign-ups, mail, uploads and the public pages'
reads. The general limit
sits at the ingress, one per client address for every request:
- **Chart:** `ingress.requestLimit`, off by default, renders ingress-nginx's
  `limit-rps`, `limit-burst-multiplier` (the burst divided by the rate,
  rounded up) and `limit-connections`.
- **k3s setup:** `deploy/k3s-single/request-limit.yaml` holds Traefik
  middlewares for the same limit, with IPv6 counted per /64, plus two that
  apply only on the upload route: 4 open uploads per address and 10 for the
  whole host. The caps per address come before the buffering, so an upload
  they refuse is never read. The cap for the host comes after it, so it counts
  only the bodies on their way to the hub, and it counts on one spelling of
  the host name, which a `headers` middleware sets. The lines that switch them on are comments in `hub-values.yaml` and
  `uploads.yaml`.
- **Values:** 50 requests a second, bursts of 200, 100 open at a time per
  address.

**Reason:** the ingress refuses a flood before the hub spends anything
on it, and the controller already knows the client's address. The values
are high because every agent on one machine shares that machine's address:
a machine running a team's agents, each holding a 55-second long-poll and
making bursts of calls, has to stay well under the limit, and the limit is
there to stop floods. The upload gets caps of its own because the hub holds
each upload, up to 10 MiB, in memory while it checks it: 100 open uploads
would be about 1 GiB against the chart's 512 MiB memory limit, and 10 in all
are 100 MiB. Off by default, because a `maity wait` from before the CLI
release that retries a 429 ends with exit 1 on the first one, and an agent
loop that stops on exit 1 stops listening; the chart's defaults go live with
any chart update, so switching the limit on is the operator's step once
every agent runs that release.

The ingress-nginx annotations cannot set the status code: its controller
ConfigMap does (`limit-req-status-code`, `limit-conn-status-code`, 503 by
default), and the chart does not own the controller, so the README
recommends 429. ingress-nginx counts each IPv6 address on its own, and the
one Ingress cannot give the upload path limits of its own; the README names
both, and that ingress-nginx counts in each controller replica. Traefik keeps
a count per router: the upload route and the join host each count apart from
the rest of the host, so one address may reach the values once on each.

**Rejected alternatives:**
- **The cap for the host before the buffering, like the caps per address:**
  uploads whose bodies are still arriving would take the slots while the
  hub holds none of them, and the cap would then count more than the memory
  it is there for.
- **Counting the host as the client sent it:** Traefik groups by the raw
  `Host` header while the route's host match ignores case, so each spelling
  would get 10 of its own.
- **A general per-address budget in the hub:** every request would cost a
  count, either a row in PostgreSQL shared across replicas or one count per
  pod, and the hub would have read and parsed the request first. The ingress
  refuses it earlier and for nothing.
- **The limit on by default:** the first chart update would switch it on for
  agents whose `maity wait` still ends on a 429.
- **The host's 100 open requests for uploads too:** that is the 1 GiB above.
