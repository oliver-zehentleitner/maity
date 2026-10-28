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
#   dump first, e.g. maity-pg-dump; unset = no dump), KUBECONFIG as usual.
# Any exit, including a failed upgrade or Ctrl-C, scales the hub back to the replicas it had.
set -uo pipefail

NAMESPACE=${NAMESPACE:-maity}
RELEASE=${RELEASE:-maity}
DEPLOYMENT=${DEPLOYMENT:-$RELEASE-maity-hub}
CHART=${CHART:-$(cd "$(dirname "$0")/../helm/maity-hub" && pwd)}
HELM_TIMEOUT=${HELM_TIMEOUT:-10m}
[ $# -gt 0 ] || { echo "usage: $0 -f values.yaml [helm upgrade arguments]" >&2; exit 2; }

replicas=$(kubectl -n "$NAMESPACE" get deploy "$DEPLOYMENT" -o jsonpath='{.spec.replicas}') || exit 1
replicas=${replicas:-1}
[ "$replicas" != 0 ] || replicas=1
restore() {
  echo "restoring $DEPLOYMENT to $replicas replica(s)"
  kubectl -n "$NAMESPACE" scale "deploy/$DEPLOYMENT" --replicas="$replicas" >/dev/null
}
trap restore EXIT

if [ -n "${DUMP_CRONJOB:-}" ]; then
  job="pre-upgrade-$(date +%H%M%S)"
  kubectl -n "$NAMESPACE" create job --from="cronjob/$DUMP_CRONJOB" "$job" &&
    kubectl -n "$NAMESPACE" wait --for=condition=complete "job/$job" --timeout=300s ||
    { echo "the dump failed, nothing was changed" >&2; trap - EXIT; exit 1; }
  echo "dump job: $job"
fi

kubectl -n "$NAMESPACE" delete job "$RELEASE-maity-hub-migrate" --ignore-not-found >/dev/null
kubectl -n "$NAMESPACE" scale "deploy/$DEPLOYMENT" --replicas=0
kubectl -n "$NAMESPACE" wait --for=delete pod -l app.kubernetes.io/component=hub --timeout=180s || true

helm -n "$NAMESPACE" upgrade "$RELEASE" "$CHART" --wait --timeout "$HELM_TIMEOUT" "$@"
status=$?

trap - EXIT
restore
if [ $status -eq 0 ]; then
  kubectl -n "$NAMESPACE" rollout status "deploy/$DEPLOYMENT" --timeout=300s
else
  echo "helm upgrade failed ($status); the hub is back on the old release" >&2
fi
exit $status
