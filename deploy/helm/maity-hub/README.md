# maity-hub Helm chart

The Maity hub on Kubernetes. It serves the API and the dashboard from one
process and runs against a PostgreSQL that already exists. The chart does
not install a database.

What it installs:

| Object | Purpose |
|---|---|
| Job `<release>-maity-hub-migrate` | `maity-hub migrate`, as a `pre-install,pre-upgrade` hook before the Deployment changes |
| Deployment `<release>-maity-hub` | one pod, `Recreate` on upgrade, non-root, read-only root filesystem |
| Service `<release>-maity-hub` | ClusterIP, port 80 → 8080 |
| Ingress (optional) | TLS, with ingress-nginx annotations for the event long-poll |
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
   workflow's run summary prints it. To build your own from the repository
   root:

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
   pull requests, contents and checks is enough.

   ```sh
   kubectl -n maity create secret generic maity-hub-forge --from-file=github-token=./github-token
   ```

   The instance key for secrets the hub stores (`MAITY_SECRET_KEY`, the
   forge webhook's secret, docs/api.md §17.4) is optional: without it no
   webhook secret can be created. 32 random bytes, base64:

   ```sh
   head -c 32 /dev/urandom | base64 > ./secret-key
   kubectl -n maity create secret generic maity-secret-key --from-file=MAITY_SECRET_KEY=./secret-key
   ```

   A value that is not exactly 32 bytes of base64 stops the hub and the
   migrate Job from starting, so a typo shows at once. Keep a copy outside
   the cluster: a lost or changed key makes every stored secret unusable (the hub logs it at startup, and each webhook
   needs a new secret). The chart has no value of its own for it; it goes
   in through `extraEnv` (below).

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
   extraEnv:
     - name: MAITY_SECRET_KEY
       valueFrom:
         secretKeyRef: {name: maity-secret-key, key: MAITY_SECRET_KEY}
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
     maity-hub owner create --handle <handle> --display-name '<Your Name>' < password-file
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
| `forge.github.existingSecret`, `.key` | none, `github-token` | the Secret holding `MAITY_FORGE_GITHUB_TOKEN` |
| `config.publicUrl` | `https://<ingress.host>` | `MAITY_PUBLIC_URL`, the address in join links; required without the Ingress |
| `config.trustedProxies` | none; required with the Ingress | `MAITY_TRUSTED_PROXIES`, the ingress controller's pod network |
| `config.allowPlainHttp` | `false` | `MAITY_ALLOW_PLAIN_HTTP`; refused with the Ingress or a non-ClusterIP Service |
| `config.dashboard` | `true` | serve the dashboard; `false` serves the API only |
| `migrate.enabled` | `true` | the hook Job; off means you migrate before every upgrade |
| `migrate.activeDeadlineSeconds` | `300` | keep it under Helm's `--timeout` |
| `ingress.joinHost` | none | an optional second host for the agent join only (`MAITY_JOIN_URL`, docs/api.md §1.1); it joins the Ingress rules and the certificate (a Secret of your own must cover it), and the hub routes between the hosts; it must differ from `ingress.host` and needs the Ingress enabled (with your own Ingress, set `MAITY_JOIN_URL` through `extraEnv`) |
| `ingress.annotations` | ingress-nginx long-poll settings | merged with yours; set a key to `null` to drop it |
| `ingress.tls.enabled` | `true` | `false` only with TLS in front of the controller; the public URL stays `https://` |
| `networkPolicy.enabled`, `.from` | `true`, the `ingress-nginx` namespace | who may connect to the hub besides the test pod |
| `service.type`, `.annotations` | `ClusterIP`, none | |
| `extraEnv`, `extraVolumes`, `extraVolumeMounts` | `[]` | for the hub and the migrate Job |
| `resources` | 50m / 128Mi requested, 512Mi limit | |
| `terminationGracePeriodSeconds` | `65` | lets open long-polls (up to 55 s) finish |

The chart refuses to render:
- without an image, the database Secret, or a public URL;
- with the Ingress but no `trustedProxies`: the hub would see plain HTTP
  and the controller's address for every client, refuse every login and
  join, or put all clients into one rate-limit bucket;
- with `allowPlainHttp` together with the Ingress or a NodePort or
  LoadBalancer Service.

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

The default annotations are for ingress-nginx, the most common controller
until now. Upstream ingress-nginx (`kubernetes/ingress-nginx`) has been
retired since March 2026: no further releases or security fixes. A new
cluster should use a maintained controller. The chart's Ingress is a plain
`networking.k8s.io/v1` Ingress that any controller serves; set
`ingress.className`, set the controller's own equivalents of the three
annotations, and set `null` for the nginx keys if they bother you. A
controller that only speaks Gateway API needs an HTTPRoute the chart does
not ship yet (`hub/context/kubernetes.md`).

## Behaviour worth knowing

- **One pod, always.** The long-poll notifier, the request-signing nonce
  window, the rate limits and the probe worker live in the process. A
  second pod, even during a rolling update, is not safe yet. Upgrades
  therefore use `Recreate`, and there is no replica value
  (`hub/context/kubernetes.md`).
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
  Deployment to 0, runs `helm upgrade` (the hook migrates alone), and scales
  back to the replicas it had on any exit, a failed upgrade and Ctrl-C
  included. Helm only starts once the hub's pods are verifiably gone; a failed
  scale-down or pods still there after `STOP_TIMEOUT` end the script first.
  The exit status is Helm's own when the upgrade failed, 3 when scaling back
  failed, 4 when the hub did not become ready, 0 only when everything worked.
  `DUMP_CRONJOB=<cronjob>` takes a dump job first, and
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
