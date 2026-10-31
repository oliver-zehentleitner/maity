# Maity on a single small instance with k3s

The manifests for running the hub on one small VM with k3s. They are
tested on k3s v1.36.5+k3s1, cert-manager v1.20.4 and PostgreSQL 17.10:
- Traefik and klipper, bundled with k3s
- cert-manager with Let's Encrypt
- PostgreSQL 17 as a StatefulSet
- a daily `pg_dump` and a tar of the attachments
- the hub's Helm chart

The walkthrough, with the secrets and the order, is in
[`docs/install/README.md`, "Kubernetes on a single small instance (k3s)"](../../docs/install/README.md#kubernetes-on-a-single-small-instance-k3s).

| File | What |
|---|---|
| `traefik-config.yaml` | HelmChartConfig for k3s's Traefik: `externalTrafficPolicy: Local`, HTTP → HTTPS at the entry point. Goes to `/var/lib/rancher/k3s/server/manifests/` on the host |
| `issuer.yaml` | ClusterIssuer `letsencrypt` (HTTP-01 via Traefik) |
| `postgres.yaml` | PostgreSQL 17 Service and StatefulSet, password from the Secret `maity-postgres` |
| `postgres-netpol.yaml` | NetworkPolicy: only the hub, its migrate Job and the backup Job reach PostgreSQL |
| `attachments.yaml` | the volume of the hub's attachment store (10 GiB), mounted by the chart's `attachments.existingClaim` |
| `backup.yaml` | daily `pg_dump` CronJob and a tar of the attachment volume, into the backup volume, the newest 14 kept |
| `restore-attachments.yaml` | the Job that puts one night's attachment files back (not applied as it stands) |
| `cert.yaml` | the Certificate for the apex, `www` and the join host, and the `www` → apex redirect |
| `hub-values.yaml` | values for [`deploy/helm/maity-hub`](../helm/maity-hub/README.md) |

Replace `maity.example.org` and the image digest before applying. No file
holds a secret: the two Secrets are created by hand, as the walkthrough
shows.
