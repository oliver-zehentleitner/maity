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
| ServiceAccount | without an API token; the hub never talks to the Kubernetes API |
| Test pod (`helm test`) | `/api/v1/health` through the Service |

Secrets are not created by the chart. It refers to Secrets you create in the
release namespace, so the database URL and the forge token never pass
through values, `helm get values` or the shell history.

## Install

1. **Image.** Build the hub image from the repository root and push it to a
   registry the cluster can pull from. The project does not publish an image
   yet.

   ```sh
   docker build -f deploy/Dockerfile -t registry.example.org/maity-hub:<commit> .
   docker push registry.example.org/maity-hub:<commit>
   ```

2. **Database.** Create a database and a user in your PostgreSQL. Write the
   URL into a file, and percent-encode an `@` or `:` in the password:

   ```sh
   (umask 077; printf 'postgresql://maity:<password>@postgres.db.svc:5432/maity' > database-url)
   kubectl -n maity create secret generic maity-hub-database --from-file=database-url=./database-url
   rm database-url
   ```

   **Forge token (optional).** The token is what lets releases become
   ready: without it the probe answers `probe_not_configured`. Read access
   to pull requests, contents and checks is enough.

   ```sh
   kubectl -n maity create secret generic maity-hub-forge --from-file=github-token=./github-token
   ```

3. **Values.** A minimal `values.yaml` behind ingress-nginx with cert-manager:

   ```yaml
   image:
     repository: registry.example.org/maity-hub
     tag: "<commit>"
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
   ```

4. **Install and check:**

   ```sh
   helm install maity deploy/helm/maity-hub -n maity -f values.yaml --wait
   helm test maity -n maity
   ```

5. **First human account.** The password is read from standard input:

   ```sh
   kubectl -n maity exec -i deploy/maity-maity-hub -- \
     maity-hub owner create --handle <handle> --display-name '<Your Name>' < password-file
   ```

## Values

`values.yaml` documents every value. `values.schema.json` refuses unknown
keys and wrong types, so a typo fails `helm install` instead of being
silently ignored. These are the values that matter:

| Value | Default | Meaning |
|---|---|---|
| `image.repository` | required | the hub image |
| `image.tag` / `image.digest` | appVersion / none | a digest wins over the tag |
| `database.existingSecret`, `.key` | required, `database-url` | the Secret holding `MAITY_DATABASE_URL` |
| `forge.github.existingSecret`, `.key` | none, `github-token` | the Secret holding `MAITY_FORGE_GITHUB_TOKEN` |
| `config.publicUrl` | `https://<ingress.host>` | `MAITY_PUBLIC_URL`, the address in join links; required without the Ingress |
| `config.trustedProxies` | none; required with the Ingress | `MAITY_TRUSTED_PROXIES`, the ingress controller's pod network |
| `config.allowPlainHttp` | `false` | `MAITY_ALLOW_PLAIN_HTTP`; only for a hub nothing outside the cluster reaches |
| `config.dashboard` | `true` | serve the dashboard; `false` serves the API only |
| `migrate.enabled` | `true` | the hook Job; off means you migrate before every upgrade |
| `ingress.annotations` | ingress-nginx long-poll settings | merged with yours; set a key to `null` to drop it |
| `resources` | 50m / 128Mi requested, 512Mi limit | |
| `terminationGracePeriodSeconds` | `65` | lets open long-polls (up to 55 s) finish |
| `extraEnv` | `[]` | further environment for the hub and the Job |

The chart refuses to render without an image, the database Secret, or a
public URL. It also refuses an Ingress without `trustedProxies`: the hub
would then see plain HTTP from the controller and refuse every login and
join.

## Behaviour worth knowing

- **One pod, always.** The long-poll notifier, the request-signing nonce
  window, the rate limits and the probe worker live in the process. A
  second pod, even during a rolling update, is not safe yet. Upgrades
  therefore use `Recreate`, and the hub is unavailable for a few seconds.
  There is no replica value (`hub/context/kubernetes.md`).
- **Migrations before the rollout.** The hook Job migrates before the
  Deployment changes. If it fails, the upgrade fails and the running hub
  stays as it was. Read the log with
  `kubectl logs job/<release>-maity-hub-migrate`; the Job stays until the
  next upgrade.
- **Rollback.** `helm rollback` to an older hub version does not downgrade
  the schema. The older hub then finds a newer schema and refuses to start.
  Roll forward instead, or downgrade the schema by hand first.
- **Probes.** Readiness uses `/api/v1/health`, which answers 503 while the
  database is down or behind the migration head. Liveness uses
  `/api/v1/help`, which needs no database, so a database outage takes the
  pod out of the Service without restarting it.
- **Ingress controllers.** The long-poll needs an unbuffered response and an
  idle timeout above 55 seconds. The default annotations do that for
  ingress-nginx; another controller needs its own equivalents.

## Checks

From the repository root:

- **`deploy/helm/check.sh`** needs helm only. It lints, renders every file
  in `ci/`, and makes sure the refusals refuse.
- **`deploy/helm/kind-smoke.sh`** needs docker, kind, kubectl and helm. On a
  throwaway kind cluster with its own kubeconfig it runs: install with
  PostgreSQL, `helm test`, a login, an upgrade, and an upgrade whose
  migration fails while the hub keeps serving.

CI runs both.
