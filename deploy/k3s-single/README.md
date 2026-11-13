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
| `backup.yaml` | daily `pg_dump` CronJob and a tar of the attachment volume, encrypted to the public key in the Secret `maity-backup-key` and, with the Secret `maity-backup-signing-key`, signed, into the backup volume, the newest 14 kept |
| `restore-attachments.yaml` | the Job that puts one night's attachment files back, streamed in after they're decrypted off the instance, and refuses while the hub runs; with a ServiceAccount whose Role only reads the hub's Deployment and lists pods (applied only for a restore, deleted after it) |
| `cert.yaml` | the Certificate for the apex, `www` and the join host, and the `www` → apex redirect |
| `uploads.yaml` | the attachment upload's own route through Traefik's buffering middleware: the whole body, at most 11 MiB, is taken before the hub sees it |
| `request-limit.yaml` | one limit per client address for every request (rate, open requests, uploads), as Traefik middlewares; off until switched on ([walkthrough](../../docs/install/README.md), "The request limit") |
| `hub-values.yaml` | values for [`deploy/helm/maity-hub`](../helm/maity-hub/README.md) |

Replace `maity.example.org`, the mail values and the hub's image digest
(`hub-values.yaml`, and `restore-attachments.yaml` for a restore) before
applying. The PostgreSQL image is pinned by digest in `postgres.yaml` and
`backup.yaml`. `deploy/scripts/test-restore-blocks.sh` runs the documented
restore blocks against stub `kubectl` and checks that they stop while the hub
is not verifiably stopped, or when a backup's signature does not check out;
`deploy/scripts/test-backup-signing.sh` runs the backup Job's scripts with a real
`gpg` and checks the signatures they write. No file holds a secret: the Secrets are created by hand, as the
walkthrough shows.
