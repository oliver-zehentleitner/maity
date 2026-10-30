#!/bin/bash
# helm upgrade with the hub stopped while the migration runs.
#
# Why: the migrate hook runs while the old pod is still serving. A migration that alters busy
# tables (0060 touched project, human and membership) then deadlocks against the old pod's open
# transactions on PostgreSQL ("deadlock detected"), and the Job fails four times in a row. The old
# pod answers 503 schema_outdated once the schema has moved anyway, so stopping it first costs
# almost nothing. See hub/context/kubernetes.md.
#
# Usage: deploy/scripts/helm-upgrade.sh -f values.yaml [more helm upgrade arguments]
# Environment: NAMESPACE (maity), RELEASE (maity), DEPLOYMENT (<release>-maity-hub),
#   CHART (the chart next to this script), HELM_TIMEOUT (10m), DUMP_CRONJOB (a CronJob to run as a
#   dump first, e.g. maity-pg-dump; unset = no dump), DUMP_TIMEOUT (seconds to wait for it, 300), DUMP_REQUIRES_ATTACHMENTS (1: the
#   dump's mark must carry the attachment tar; set it when the release has attachments.existingClaim), STOP_TIMEOUT (seconds to wait for the hub's
#   pods to be gone, 180), KUBECONFIG as usual.
#
# helm upgrade only runs when the hub is verifiably stopped: a failed scale-down or pods still
# there after STOP_TIMEOUT end the script before Helm. On any exit the hub is scaled back to the
# replicas it had (a hub found at 0 stays at 0).
# Exit status: Helm's own when the upgrade failed; otherwise 3 when scaling back failed, 4 when the
# hub did not become ready, 1 for the steps before Helm, 0 only when everything worked.
set -uo pipefail

NAMESPACE=${NAMESPACE:-maity}
RELEASE=${RELEASE:-maity}
DEPLOYMENT=${DEPLOYMENT:-$RELEASE-maity-hub}
CHART=${CHART:-$(cd "$(dirname "$0")/../helm/maity-hub" && pwd)}
HELM_TIMEOUT=${HELM_TIMEOUT:-10m}
STOP_TIMEOUT=${STOP_TIMEOUT:-180}
SELECTOR="app.kubernetes.io/instance=$RELEASE,app.kubernetes.io/component=hub"
[ $# -gt 0 ] || { echo "usage: $0 -f values.yaml [helm upgrade arguments]" >&2; exit 2; }

replicas=$(kubectl -n "$NAMESPACE" get deploy "$DEPLOYMENT" -o jsonpath='{.spec.replicas}') || exit 1
replicas=${replicas:-1}

restored=0
restore() {
  [ "$restored" = 1 ] && return 0
  restored=1
  echo "scaling $DEPLOYMENT back to $replicas replica(s)"
  kubectl -n "$NAMESPACE" scale "deploy/$DEPLOYMENT" --replicas="$replicas" >/dev/null
}
# Any exit before the normal end (a failed step, Ctrl-C) puts the hub back.
on_exit() {
  status=$?
  restore || { echo "WARNING: scaling back failed; check $DEPLOYMENT" >&2; [ "$status" = 0 ] && status=3; }
  exit "$status"
}
trap on_exit EXIT
trap 'exit 130' INT TERM

case "${DUMP_TIMEOUT:-300}" in
  *[!0-9]*|'') echo "DUMP_TIMEOUT must be a number of seconds, not '${DUMP_TIMEOUT}'; nothing was changed" >&2; exit 1;;
esac
if [ -n "${DUMP_CRONJOB:-}" ]; then
  job="pre-upgrade-$(date +%H%M%S)"
  # Complete or Failed, whichever comes first: `kubectl wait` takes one condition and would sit out its whole timeout on a failed Job.
  dump_finished() {
    local end=$((SECONDS + ${DUMP_TIMEOUT:-300})) done_ failed
    while [ "$SECONDS" -lt "$end" ]; do
      done_=$(kubectl -n "$NAMESPACE" get job "$job" -o 'jsonpath={.status.conditions[?(@.type=="Complete")].status}' 2>/dev/null)
      failed=$(kubectl -n "$NAMESPACE" get job "$job" -o 'jsonpath={.status.conditions[?(@.type=="Failed")].status}' 2>/dev/null)
      [ "$done_" = True ] && return 0
      [ "$failed" = True ] && return 1
      sleep 5
    done
    return 1
  }
  { kubectl -n "$NAMESPACE" create job --from="cronjob/$DUMP_CRONJOB" "$job" && dump_finished; } ||
    { echo "the dump failed, nothing was changed" >&2; restored=1; exit 1; }
  # A Job whose pg_dump failed used to end as Complete (see deploy/k3s-single/backup.yaml). The fixed script ends with a line
  # "dump ok: <file> <bytes>" that only a finished, non-empty dump produces, and it is asked for, not its opposite: errors that
  # a later try fixed are in the log too, and a log that cannot be read or an old script without the line must stop the upgrade.
  # The log is read from the pod that succeeded (a failed earlier try is another pod of the same Job).
  dumppod=$(kubectl -n "$NAMESPACE" get pod -l "job-name=$job" --field-selector=status.phase=Succeeded -o name 2>/dev/null | head -1)
  log=""
  [ -n "$dumppod" ] && log=$(kubectl -n "$NAMESPACE" logs "$dumppod" 2>&1)
  # With attachments the mark must also carry the tar ("... attachments <bytes>"): a CronJob that still has the script without it would
  # let an upgrade run without the files being backed up.
  case "$log" in
    *"dump ok: /backups/maity-"*" attachments "[0-9]*) ;;
    *"dump ok: /backups/maity-"*)
      if [ "${DUMP_REQUIRES_ATTACHMENTS:-0}" = 1 ]; then
        echo "the dump's mark has no attachments part (the CronJob still has the script without the tar: apply deploy/k3s-single/attachments.yaml and backup.yaml first), nothing was changed" >&2
        restored=1; exit 1
      fi;;
    *) echo "the dump job's log has no 'dump ok' line (the log could not be read, or the CronJob still has the old script: apply deploy/k3s-single/backup.yaml first), nothing was changed" >&2
       restored=1; exit 1;;
  esac
  echo "dump job: $job"
fi

kubectl -n "$NAMESPACE" delete job "$RELEASE-maity-hub-migrate" --ignore-not-found >/dev/null ||
  { echo "could not remove the old migrate Job" >&2; restored=1; exit 1; }

# Scale down only when the Deployment wants replicas; whatever it wants, Helm starts only when no
# pod of the release is left, so a hub found at 0 with pods still terminating is not migrated against.
if [ "$replicas" != 0 ]; then
  kubectl -n "$NAMESPACE" scale "deploy/$DEPLOYMENT" --replicas=0 ||
    { echo "could not scale $DEPLOYMENT to 0; no upgrade was started" >&2; exit 1; }
fi
waited=0
while :; do
  pods=$(kubectl -n "$NAMESPACE" get pods -l "$SELECTOR" -o name) ||
    { echo "could not list the hub's pods; no upgrade was started" >&2; exit 1; }
  [ -z "$pods" ] && break
  if [ "$waited" -ge "$STOP_TIMEOUT" ]; then
    echo "the hub's pods are still there after ${STOP_TIMEOUT}s ($pods); no upgrade was started" >&2
    exit 1
  fi
  sleep 2; waited=$((waited + 2))
done
echo "the hub is stopped"

helm -n "$NAMESPACE" upgrade "$RELEASE" "$CHART" --wait --timeout "$HELM_TIMEOUT" "$@"
helm_status=$?
[ "$helm_status" = 0 ] || echo "helm upgrade failed ($helm_status); the hub is scaled back to $replicas replica(s) as it is deployed now (check helm history)" >&2

status=$helm_status
restore || { echo "scaling back failed" >&2; [ "$status" = 0 ] && status=3; }
if [ "$replicas" != 0 ]; then
  kubectl -n "$NAMESPACE" rollout status "deploy/$DEPLOYMENT" --timeout=300s ||
    { echo "$DEPLOYMENT did not become ready" >&2; [ "$status" = 0 ] && status=4; }
fi
exit "$status"
