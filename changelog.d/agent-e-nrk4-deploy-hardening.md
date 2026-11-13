### Changed

- deploy: `deploy/scripts/helm-upgrade.sh` takes a dump before every upgrade by default, from the CronJob `maity-pg-dump`
  (`DUMP_CRONJOB` names another), and stops before it changes anything when that CronJob is missing or the dump fails.
  `NO_DUMP=1` skips the dump. Upgrade note: a cluster without such a CronJob (not the k3s setup) now sets `NO_DUMP=1`
  after taking its own backup, or names its CronJob with `DUMP_CRONJOB`.
- deploy: the PostgreSQL image is pinned by digest: `postgres:17.10@sha256:7958605b…` in the k3s manifests and the kind
  smoke test, `postgres:17.12@sha256:dbb9623d…` in `deploy/docker-compose.yml`, which used the moving tag `17` (17.12
  when pinned, so an existing Compose volume stays on its minor version or moves up).
- deploy: `deploy/runner/install-services.sh` reads the registration token from standard input (asked without echo at a
  terminal) or `RUNNER_TOKEN`, and hands it to `config.sh` through its environment instead of `--token`.

### Security

- deploy: `deploy/k3s-single/restore-attachments.yaml` checks through the Kubernetes API, right before it empties the
  attachment volume, that the hub's Deployment wants 0 replicas and no hub pod is left, and refuses otherwise with the
  volume unchanged. It runs the hub's image and brings a ServiceAccount whose Role only reads the hub's Deployment and
  lists pods. Upgrade note: put the hub's image digest (as in `hub-values.yaml`) into the file before a restore, and
  delete it with `kubectl delete -f` afterwards, as the documented block does.
- docs: the documented restore blocks name the instance's kube context on every `kubectl`, and check that the hub is
  stopped before anything is restored; a new step after a restore revokes every agent's credentials or applies again
  the revocations, isolations, pauses, removals and suspensions made after the dump's time (docs/install/README.md,
  "After a restore").
