# maity-hub Helm chart

The Maity hub on Kubernetes. It serves the API and the dashboard from one
process and runs against a PostgreSQL that already exists. The chart does
not install a database.

What it installs:

| Object | Purpose |
|---|---|
| Job `<release>-maity-hub-migrate` | `maity-hub migrate`, as a `pre-install,pre-upgrade` hook before the Deployment changes |
| Deployment `<release>-maity-hub` | one pod (`Recreate`) unless `replicas` says more (rolled one at a time), non-root, read-only root filesystem |
| PodDisruptionBudget (with `replicas` above 1) | keeps one hub pod up through a node drain |
| Service `<release>-maity-hub` | ClusterIP, port 80 → 8080 |
| Ingress (optional) | TLS, with ingress-nginx annotations for the event long-poll and the attachment upload's body size |
| NetworkPolicy (on by default) | only the ingress controller's namespace and the release's test pod reach the hub |
| ServiceAccount | without an API token; the hub never talks to the Kubernetes API |
| Test pod (`helm test`) | `/api/v1/health` through the Service |

Secrets are not created by the chart. It refers to Secrets you create in the
release namespace, so the database URL and the forge token never pass
through values, `helm get values` or the shell history.

## Prerequisites

The steps below use a fresh Vultr Kubernetes Engine (VKE) cluster as the
example; any cluster with the same pieces works.

- **An ingress controller** with an IngressClass, its Service of type
  `LoadBalancer`. It must pass the client address on (see "Client
  addresses") and must not buffer responses (see "Ingress controllers").
- **TLS for the host name:** cert-manager with a ClusterIssuer (the example
  calls it `letsencrypt`), or a TLS Secret you create yourself under the
  name in `ingress.tls.secretName`. With `ingress.joinHost`, the
  certificate must cover that host name too.
- **A DNS record** for the host name, pointing at the controller's load
  balancer.
- **A registry** the cluster can pull from, and a docker-registry Secret
  for it if it is private.
- **PostgreSQL** reachable from the cluster, with a database and a user for
  the hub. A managed database with TLS is the usual case.
- **A CNI that enforces NetworkPolicy** (Calico or Cilium do), or
  `networkPolicy.enabled: false` and the same restriction made some other
  way. The default policy admits the controller's namespace. Traffic from a
  node address (a NodePort or LoadBalancer Service, or a controller on
  `hostNetwork`) matches no namespace and is dropped. Add an `ipBlock` for
  the nodes' addresses to `networkPolicy.from`, or disable the policy.
- **The cluster's pod network**, for `config.trustedProxies`:
  `kubectl get nodes -o jsonpath='{.items[*].spec.podCIDR}'` lists each
  node's share of it; use the range that covers them all.

## Install

1. **Namespace:**

   ```sh
   kubectl create namespace maity
   ```

2. **Image.** Releases are published as `ghcr.io/oliver-zehentleitner/maity-hub`,
   tagged with the version and the full commit SHA and never `latest`. The
   workflow `publish-image` builds them; until its first release you build
   the image yourself. Pin it by digest (`image.digest`) when you can; the
   workflow's run summary prints it. Each published digest is signed with
   cosign, keyless, by that workflow on a `v*` tag or on `main`; check the
   signature before you pin a digest:

   ```sh
   cosign verify ghcr.io/oliver-zehentleitner/maity-hub@sha256:<digest> \
     --certificate-oidc-issuer https://token.actions.githubusercontent.com \
     --certificate-identity-regexp '^https://github\.com/oliver-zehentleitner/maity/\.github/workflows/publish-image\.yml@refs/(tags/v[^/]+|heads/main)$'
   ```

   This needs cosign v3 or later: the workflow stores the signature in the
   newer bundle format, which cosign 2.x does not find.

   An image whose signature names another workflow or another ref did not
   come from a release or from `main`; don't run it. To build your own from
   the repository root:

   ```sh
   docker build -f deploy/Dockerfile -t registry.example.org/maity-hub:<commit> .
   docker push registry.example.org/maity-hub:<commit>
   ```

   For a private registry, create the pull Secret in the namespace:
   `kubectl -n maity create secret docker-registry registry-credentials …`.

3. **Database.** Write the URL into a file, so it never enters the shell
   history, and percent-encode an `@` or `:` in the password. For a managed
   PostgreSQL with TLS on its own port:

   ```sh
   (umask 077; printf 'postgresql://maity:<password>@db.example.org:16751/maity?sslmode=require' > database-url)
   kubectl -n maity create secret generic maity-hub-database --from-file=database-url=./database-url
   rm database-url
   ```

   `sslmode=require` encrypts but does not check the server's certificate.
   To check it, put the provider's CA into a Secret, mount it with
   `extraVolumes` and `extraVolumeMounts` (the hub and the migrate Job both
   get them), and use
   `?sslmode=verify-full&sslrootcert=/etc/maity/db-ca/ca.crt`:

   ```sh
   kubectl -n maity create secret generic maity-hub-db-ca --from-file=ca.crt=./ca.crt
   ```

   **Forge token (optional).** It is for the forge probe, which comes with a
   later hub version: with it, releases can become ready. Read access to
   pull requests, contents and checks is enough. It reads only for projects
   in the namespaces you list in `forge.github.instanceNamespaces` (your
   own); every other project connects its repository with its owner's
   GitHub App installation or token.

   ```sh
   kubectl -n maity create secret generic maity-hub-forge --from-file=github-token=./github-token
   ```

   The instance key for secrets the hub stores (`MAITY_SECRET_KEY`: the
   forge webhook's secret, a stored SMTP password, second-factor secrets;
   docs/api.md §16.2, §17.4) is optional: without it none of those can be
   stored, and the second factor `required_admins` refuses to start. 32
   random bytes, base64:

   ```sh
   head -c 32 /dev/urandom | base64 > ./secret-key
   kubectl -n maity create secret generic maity-secret-key --from-file=secret-key=./secret-key
   ```

   A value that is not exactly 32 bytes of base64 stops the hub and the
   migrate Job from starting, so a typo shows at once. Keep a copy outside
   the cluster: a lost or changed key makes every stored secret unusable (the hub logs it at startup, and each webhook
   needs a new secret). In the values it is `secretKey.existingSecret`
   (below); the Secret's key defaults to `secret-key`, set `secretKey.key` if you named it differently.

4. **Values.** A `values.yaml` behind an ingress controller with
   cert-manager:

   ```yaml
   image:
     repository: registry.example.org/maity-hub
     tag: "<commit>"
   imagePullSecrets:
     - name: registry-credentials
   database:
     existingSecret: maity-hub-database
   forge:
     github:
       existingSecret: maity-hub-forge
       instanceNamespaces: your-handle  # the token reads only your own projects
   config:
     # The ingress controller's pods: the cluster's pod network.
     trustedProxies: 10.244.0.0/16
   ingress:
     enabled: true
     className: nginx
     host: maity.example.org
     annotations:
       cert-manager.io/cluster-issuer: letsencrypt
   networkPolicy:
     from:
       - namespaceSelector:
           matchLabels:
             kubernetes.io/metadata.name: ingress-nginx   # your controller's namespace
   # The instance key, when created in step 3:
   secretKey:
     existingSecret: maity-secret-key
   # With sslmode=verify-full:
   extraVolumes:
     - name: db-ca
       secret: {secretName: maity-hub-db-ca}
   extraVolumeMounts:
     - {name: db-ca, mountPath: /etc/maity/db-ca, readOnly: true}
   ```

5. **Install and check.** The `--timeout` stays above the migrate Job's
   deadline (`migrate.activeDeadlineSeconds`, 300 s):

   ```sh
   helm install maity deploy/helm/maity-hub -n maity -f values.yaml --wait --timeout 10m
   helm test maity -n maity --logs
   ```

6. **First human account.** The password is read from standard input:

   ```sh
   kubectl -n maity exec -i deploy/maity-maity-hub -- \
     maity-hub owner create --handle <handle> --display-name '<Your Name>' \
       --email <you@example.org> < password-file
   ```

Upgrades are the same command with `helm upgrade`, also with
`--timeout 10m`. Use `deploy/scripts/helm-upgrade.sh -f values.yaml` instead
when the release brings a migration: it stops the hub while the migration
runs and starts it again on any exit (see "The migration and the running
pod" below).

## Values

`values.yaml` documents every value. `values.schema.json` refuses unknown
keys and wrong types, so a typo fails `helm install` instead of being
silently ignored. These are the values that matter:

| Value | Default | Meaning |
|---|---|---|
| `image.repository` | required | the hub image |
| `image.tag` / `image.digest` | appVersion / none | a digest wins over the tag |
| `imagePullSecrets` | `[]` | `[{name: …}]` |
| `database.existingSecret`, `.key` | required, `database-url` | the Secret holding `MAITY_DATABASE_URL` |
| `database.poolSize`, `.maxOverflow` | hub default (16, 16) | `MAITY_DB_POOL_SIZE`, `MAITY_DB_MAX_OVERFLOW`: each pod's connections, shared by its workers (see Several pods) |
| `replicas` | `1` | hub pods and `MAITY_REPLICAS`; above 1 only with PostgreSQL and without `attachments.existingClaim` (see Several pods) |
| `config.workers` | `1` | `MAITY_WORKERS`, serving processes per pod; above 1 only with PostgreSQL |
| `topologySpreadConstraints` | `[]` | with more than one replica: spread over nodes by default; set to replace it |
| `forge.github.existingSecret`, `.key` | none, `github-token` | the Secret holding `MAITY_FORGE_GITHUB_TOKEN` |
| `forge.github.instanceNamespaces` | empty | `MAITY_FORGE_INSTANCE_NAMESPACES`: the operator's own namespaces, comma separated, the only ones the token reads for (public repositories only); empty, it serves no project |
| `attachments.existingClaim`, `.mountPath` | none, `/var/lib/maity/attachments` | the PersistentVolumeClaim of the local attachment store (docs/api.md §8.7), mounted into the hub, not the migrate Job, and `MAITY_ATTACHMENT_DIR`. What one project may store is the hub's limit `max_attachment_storage_per_project` (§16.5), set under Limits or by `MAITY_MAX_ATTACHMENT_STORAGE_PER_PROJECT` in `extraEnv`. A directory the hub cannot write stops the new hub at its start: with `Recreate` the old pod is already gone, so the hub is down, and the migration has already run. The way back is forward: fix the volume or `attachments.mountPath` and run `helm upgrade` again with the same image. `helm rollback` to the old image works only if the upgrade did not move the schema (see Rollback below); otherwise the old image needs the dump restored; empty claim: attachments off. The files are not in the database: back the volume up with it |
| `attachments.store` | `local` | `MAITY_ATTACHMENT_STORE`: `local` keeps the files on the claim, for one replica; `s3` keeps them in a bucket that several replicas share (below, and *Moving attachments to S3*) |
| `attachments.s3.bucket`, `.endpoint`, `.region`, `.prefix`, `.allowHttp` | none (bucket required with `s3`), AWS, none, none, `false` | `MAITY_ATTACHMENT_S3_BUCKET`, `_ENDPOINT` (an https URL without a path), `_REGION`, `_PREFIX`, `_ALLOW_HTTP` (plain http only to a host inside the cluster) |
| `attachments.s3.existingSecret`, `.accessKeyIdKey`, `.secretAccessKeyKey` | none, `MAITY_ATTACHMENT_S3_ACCESS_KEY_ID`, `MAITY_ATTACHMENT_S3_SECRET_ACCESS_KEY` | the Secret holding the bucket's credentials, by reference; none: the client's own chain (an instance role) |
| `secretKey.existingSecret`, `.key` | none, `secret-key` | the Secret holding `MAITY_SECRET_KEY`, the instance key for stored secrets; moving it from `extraEnv`: drop it there in the same upgrade, the chart does not dedupe; a Secret created with the first README holds the key as `MAITY_SECRET_KEY`, then set `secretKey.key: MAITY_SECRET_KEY` |
| `mail.signingKeySecret.existingSecret`, `.key` | none, `mail-signing-key` | the Secret holding `MAITY_MAIL_SIGNING_KEY` (32 bytes or more, base64); without it the hub sends no mail |
| `mail.host`, `.port`, `.tls` | none, `587`, `starttls` | `MAITY_SMTP_HOST`, `_PORT`, `_TLS` (`starttls`, `implicit` or `none`); empty host: no SMTP env, the admin settings apply; with a host, port and TLS always come from here. Moving these from `extraEnv`: drop them from `extraEnv` in the same upgrade, the chart does not dedupe |
| `mail.username`, `.from`, `.replyTo` | none | `MAITY_SMTP_USERNAME`, `_FROM`, `_REPLY_TO` |
| `mail.passwordSecret.existingSecret`, `.key` | none, `smtp-password` | the Secret holding `MAITY_SMTP_PASSWORD` |
| `config.publicUrl` | `https://<ingress.host>` | `MAITY_PUBLIC_URL`, the address in join links; required without the Ingress |
| `config.trustedProxies` | none; required with the Ingress | `MAITY_TRUSTED_PROXIES`, the ingress controller's pod network |
| `config.allowPlainHttp` | `false` | `MAITY_ALLOW_PLAIN_HTTP`; refused with the Ingress or a non-ClusterIP Service |
| `config.dashboard` | `true` | serve the dashboard; `false` serves the API only |
| `migrate.enabled` | `true` | the hook Job; off means you migrate before every upgrade |
| `migrate.activeDeadlineSeconds` | `300` | keep it under Helm's `--timeout` |
| `ingress.joinHost` | none | an optional second host for the agent join only (`MAITY_JOIN_URL`, docs/api.md §1.1); it joins the Ingress rules and the certificate (a Secret of your own must cover it), and the hub routes between the hosts; it must differ from `ingress.host` and needs the Ingress enabled (with your own Ingress, set `MAITY_JOIN_URL` through `extraEnv`) |
| `ingress.annotations` | ingress-nginx long-poll settings and `proxy-body-size: 11m` | merged with yours; set a key to `null` to drop it |
| `ingress.tls.enabled` | `true` | `false` only with TLS in front of the controller; the public URL stays `https://` |
| `networkPolicy.enabled`, `.from` | `true`, the `ingress-nginx` namespace | who may connect to the hub besides the test pod |
| `service.type`, `.annotations` | `ClusterIP`, none | |
| `extraEnv`, `extraVolumes`, `extraVolumeMounts` | `[]` | for the hub and the migrate Job; a `ReadWriteOnce` claim here must land both on one node |
| `resources` | 50m / 128Mi requested, 512Mi limit | |
| `terminationGracePeriodSeconds` | `65` | lets open long-polls (up to 55 s) finish |

The chart refuses to render:
- without an image, the database Secret, or a public URL;
- with the Ingress but no `trustedProxies`: the hub would see plain HTTP
  and the controller's address for every client, refuse every login and
  join, or put all clients into one rate-limit bucket;
- with `allowPlainHttp` together with the Ingress or a NodePort or
  LoadBalancer Service.

The registration, terms, second-factor, limit and public-page settings have no
value of their own here. Set them in `extraEnv`, or as instance admin where the
dashboard offers them; what each does is in
[`hub/README.md`](../../../hub/README.md#settings-for-a-public-instance), the
order in
[Opening registration](../../../docs/install/README.md#opening-registration):

```yaml
extraEnv:
  - {name: MAITY_REGISTRATION, value: open}
  - {name: MAITY_SIGN_IN_SECOND_FACTOR, value: required_admins}
  - {name: MAITY_PUBLIC_PAGES, value: "on"}
```

## Client addresses

The hub rate-limits logins and joins per client address, and it takes that
address from `X-Forwarded-For` only when the connection comes from
`trustedProxies`. The controller has to know the real address first.
Behind a cloud load balancer with the default
`externalTrafficPolicy: Cluster`, the controller sees a node's address
instead, and every client then shares one bucket.

On VKE, either:

- **PROXY protocol:** the annotation
  `service.beta.kubernetes.io/vultr-loadbalancer-proxy-protocol: "true"` on
  the controller's Service, and the controller told to expect it (for
  ingress-nginx: `use-proxy-protocol: "true"` in its ConfigMap). Both sides
  have to change together, or every request fails while only one has.
- **`externalTrafficPolicy: Local`** on the controller's Service: the
  client address survives, and the load balancer sends traffic only to
  nodes that run a controller pod.

The kind smoke test cannot show this: `kubectl port-forward` arrives from
loopback.

## Ingress controllers

The event long-poll holds a request open for up to 55 seconds. The
controller must allow at least that per request (the defaults give 75 s)
and must pass the response on unbuffered.

An attachment upload is one body of up to 10 MiB (`docs/api.md` §8.7).
The controller must let it through: ingress-nginx refuses bodies over 1 MiB
unless told otherwise, so the defaults set `proxy-body-size` to `11m`. On
k3s's Traefik, `deploy/k3s-single/uploads.yaml` gives the upload its own
route, which buffers the body before it reaches the hub.

The hub has no general request budget. Its own limits are per route,
among them sign-ins, codes, sign-ups, mail, uploads and the public pages'
reads. The general limit belongs to the controller: one limit
per client address for every request. `ingress.requestLimit` sets it for
ingress-nginx (`limit-rps`, `limit-burst-multiplier`, `limit-connections`).
It is off by default. Switch it on only once every agent runs a `maity`
whose `maity wait` retries a 429. An older one ends its wait on the first
refusal. Some things to know:

- **Status code:** ingress-nginx refuses with `503` unless its controller
  ConfigMap sets `limit-req-status-code` and `limit-conn-status-code` to
  `429`, which is better: clients take a 429 as "slow down", a 503 as an
  outage.
- **IPv6:** ingress-nginx counts each IPv6 address on its own, not per
  network.
- **Replicas:** ingress-nginx counts in each controller replica, so with
  several a client gets the values once per replica.
- **The upload route:** ingress-nginx cannot give the upload a limit of its
  own within this one Ingress, so uploads count against `inFlight` like any
  request.
- **Traefik:** `deploy/k3s-single/request-limit.yaml` does the same and
  more.
- **Every agent on one machine shares that machine's address,** so the
  values leave room for a whole team.

The default annotations are for ingress-nginx, the most common controller
until now. Upstream ingress-nginx (`kubernetes/ingress-nginx`) has been
retired since March 2026: no further releases or security fixes. A new
cluster should use a maintained controller. The chart's Ingress is a plain
`networking.k8s.io/v1` Ingress that any controller serves; set
`ingress.className`, set the controller's own equivalents of the four
annotations, and set `null` for the nginx keys if they bother you. A
controller that only speaks Gateway API needs an HTTPRoute the chart does
not ship yet (`hub/context/kubernetes.md`).

## Moving attachments to S3

The files on the claim are copied into the bucket by the hub itself, under the same key
(`<prefix>/<project id>/<attachment id>`). `maity-hub attachments copy-to-s3` skips an object
that is already there with the same SHA-256, so it can run as often as needed, and it never
changes the files on the claim. An object the hub wrote with another SHA-256 is never
overwritten: it is reported as different, and the command ends with exit 1. Keys are immutable
attachment ids, so treat the file on the claim as the suspect one: compare it with the object
(`sha256sum` against the object's `x-amz-meta-sha256`), and keep the object. A file whose
attachment is deleted, or has no row, is not copied: under `s3` the hub deletes only in the
bucket, and a redacted attachment must not come back. With `--apply` it then removes from the
bucket what was deleted since an earlier run: while the hub serves from the claim, its
deletions reach only the claim. The object of a deleted attachment goes at once, an object no
row names once it is older than 30 minutes; a folder of a project the database does not know
is left alone and named once in the log. Without `--apply` it counts those removals too. After each copy it checks the object's
size and the SHA-256 it wrote as metadata (the bytes themselves are protected in transit by the
client's checksum). A folder no project has (`lost+found`) is left alone and named in the log; a
project's folder it cannot read counts as failed, the rest is copied.
Without `--apply` it only counts.

1. Upgrade to a hub version that has the `s3` store, still with `attachments.store: local`, and
   with the `attachments.s3.*` values set: the chart renders them whenever a bucket is set, and
   the hub reads them only under `s3`. The Secret named in `attachments.s3.existingSecret` must
   exist first: the pod does not start without it, even under `local`.
2. In the hub pod: `MAITY_ATTACHMENT_STORE=s3 maity-hub attachments copy-to-s3`, then the same
   with `--apply`. The store setting is the command's alone; the hub keeps serving from the claim,
   and an attachment it deletes from now on is removed from the claim only: its copy stays in
   the bucket until the next run with `--apply` or the first sweep under `s3`. Go on with step 3
   right after this one.
3. `helm upgrade` with `attachments.store: s3`, the claim still set: the hub now serves from the bucket, and the claim stays mounted for the next step. Its first attachment sweep under `s3`, within five minutes, removes from the bucket what was deleted since step 2: a deleted attachment's object at once, an object no row names once it is 30 minutes old.
4. In the new pod: `maity-hub attachments copy-to-s3 --apply` once more, for the uploads between
   steps 2 and 3; it should copy only those. Run it right away: until it has run, the hub
   cannot serve those uploads.
5. `helm upgrade` with `attachments.existingClaim` empty. Keep the volume until the backups no
   longer need it.

Between the last run of step 2 and step 3, a deletion leaves its object in the bucket; after
step 3 the hub's sweep removes it within minutes.

There is no copy back. Going back to `local` (a `helm rollback`, or `attachments.store: local`)
works only while the claim is still mounted, and the uploads since step 3 are then only in the
bucket.

A move given up before step 3, or rolled back to `local`, leaves objects in the bucket that may
belong to attachments deleted since the last run, since no sweep under `s3` runs to remove them:
run step 2 with `--apply` once more, which removes them, or empty the bucket's prefix or delete
the bucket. After a rollback from step 3 on, the uploads since then are only there: take what is
still needed before emptying it.

With the bucket's versioning on, a deletion by the hub leaves a noncurrent version behind: a
lifecycle rule that expires noncurrent versions is what makes a deleted attachment gone.

## Behaviour worth knowing

- **One pod by default.** With `replicas: 1` the pod is replaced with
  `Recreate`: SQLite and a local attachment volume are one pod's. More pods
  are opt-in, see Several pods below.
- **The schema and the running pod.** A hub serves only on exactly the
  schema head of its own version. Once the hook has migrated, the old pod's
  `/api/v1/health` answers 503 `schema_outdated`. It leaves the Service, and
  `Recreate` replaces it. An upgrade with a migration is therefore
  unavailable for the migration's duration plus the new pod's start.
- **The migration and the running pod.** The migrate hook runs while the old
  pod still serves. A migration that alters tables the hub reads and writes
  all the time can then deadlock against the old pod's open transactions
  (PostgreSQL: `deadlock detected`, the Job fails on every retry; 0060, the
  project namespace, did). The old pod answers 503 as soon as the schema has
  moved, so stopping it first costs almost no extra downtime:
  `deploy/scripts/helm-upgrade.sh -f values.yaml [helm arguments]` scales the
  Deployment to 0, runs `helm upgrade` (the hook migrates alone), and then
  runs the replicas the release renders (Helm sets them, so a changed
  `replicas` takes effect), also when the rollout check after Helm fails
  (exit 4; the way back is `helm rollback`). When it ends before Helm or Helm
  fails, Ctrl-C included, it scales back to the replicas it had; a hub found
  at 0 stays at 0. Helm only starts once the hub's pods are verifiably gone; a failed
  scale-down or pods still there after `STOP_TIMEOUT` end the script first.
  The exit status is Helm's own when the upgrade failed, 3 when scaling back
  failed, 4 when the hub did not become ready, 0 only when everything worked.
  `DUMP_CRONJOB=<cronjob>` takes a dump job first (waiting up to `DUMP_TIMEOUT` seconds, 300 by default; `DUMP_REQUIRES_ATTACHMENTS=1` also demands the attachment tar in its mark), and
  `deploy/scripts/test-helm-upgrade.sh` runs the failure paths against stub
  `kubectl` and `helm`. A release whose migration touches no busy table can
  use plain `helm upgrade`.
- **Rollback.** There is no schema downgrade: `maity-hub` has `serve`,
  `migrate` and `owner`, and the hook runs only on install and upgrade.
  `helm rollback` to a hub version with an older schema starts that version
  against the newer schema; it refuses to serve (`SchemaNotCurrentError`)
  and the pod crash-loops. Roll back only to a version with the same
  schema head, and otherwise fix forward with a new upgrade.
- **Probes.** Readiness uses `/api/v1/health`, which answers 503 while the
  database is down or behind the migration head. Liveness and startup use
  `/api/v1/help`, which needs no database, so a database outage takes the
  pod out of the Service without restarting it.

## Several pods

`replicas` above 1 runs several hub pods against one PostgreSQL. They share
wake-ups, request nonces, rate limits, worker passes and the forge budget
through the database (`hub/context/replicas.md`).

- **Needs:** PostgreSQL, and attachments off the pod's volume (S3) or off
  altogether. The chart refuses `attachments.existingClaim` with more than one
  replica; the hub refuses to start on another database or with a local
  attachment directory.
- **Upgrades:** a release without a migration rolls one pod at a time
  (`maxUnavailable: 0`, `maxSurge: 1`). A release with a migration still goes
  through `deploy/scripts/helm-upgrade.sh`, which stops every pod and starts
  the replicas the release renders (as many as it found when Helm fails).
- **Drains and nodes:** a PodDisruptionBudget keeps one pod up; the pods
  spread over nodes where they can (`topologySpreadConstraints` replaces it).
- **Connections:** the hub asks up to
  pods × (`config.workers` × (pool share + overflow share + 2 + 1) + 1)
  connections: each worker its share of `database.poolSize` and
  `database.maxOverflow` (divided by the workers, rounded down), two for the
  shared counters and one listener, each pod one more for the readiness probe. With more than one
  replica, pods is replicas + 1, for the surge pod of a rolling update. Keep
  that under the database's `max_connections` less its reserved connections;
  the hub warns at its start when it is not. Example: 3 replicas with 2
  workers and the default 16 + 16 ask 4 × (2 × (8 + 8 + 2 + 1) + 1) = 156.
  Each worker splits its pool share between its two engines: the async
  engine, where every call authenticates, takes 8 of it but at most half, and
  the sync engine, where the route bodies run, the rest and the whole
  overflow. A pool lowered to 8 gives 4 + 4 per worker; with 2 workers, 2 + 2.

## When an install or upgrade fails

- **Read the migration's log first:**
  `kubectl -n maity logs job/maity-maity-hub-migrate`. The Job stays until
  the next attempt replaces it.
- **A failed first install** (`helm status` says `failed`): fix the cause,
  then `helm uninstall maity -n maity` and install again. The Secrets you
  created are not part of the release and stay.
- **A failed upgrade:** the running hub is untouched when the hook failed,
  so fix the cause and run the same `helm upgrade` again. If the migrate log
  says `deadlock detected`, run it through `deploy/scripts/helm-upgrade.sh`
  instead.
- **`pending-install` or `pending-upgrade`**, when Helm itself was
  interrupted: `helm history maity -n maity` shows the last deployed
  revision. `helm rollback maity <that revision> -n maity` clears the
  pending state. The rollback rule above still applies: only roll back to
  a revision with the same schema head.

## Checks

From the repository root:

- **`deploy/helm/check.sh`** needs helm only. It lints, renders every file
  in `ci/`, and makes sure the refusals refuse.
- **`deploy/helm/kind-smoke.sh`** needs docker, kind, kubectl and helm. On a
  throwaway kind cluster with its own kubeconfig it runs:
  1. install with PostgreSQL;
  2. `helm test`;
  3. the NetworkPolicy: the `ingress-nginx` namespace reaches the hub,
     another namespace does not;
  4. a login;
  5. an upgrade;
  6. an upgrade whose migration fails while the hub keeps serving.

CI runs both.
