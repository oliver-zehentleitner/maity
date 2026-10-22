#!/usr/bin/env bash
# The chart on a real cluster: a throwaway kind cluster, PostgreSQL in it,
# the hub image built from this checkout, then install, test, a human login,
# an upgrade, and an upgrade whose migration fails while the hub stays up.
# Needs docker, kind, kubectl and helm. The cluster gets its own kubeconfig
# in a temporary directory and is deleted on exit; no other cluster or
# kubeconfig is touched.
# Usage: deploy/helm/kind-smoke.sh [cluster-name]    exit 0 = all held
set -euo pipefail

name="${1:-maity-helm-smoke}"
root="$(cd "$(dirname "$0")/../.." && pwd)"
chart="$root/deploy/helm/maity-hub"
image="maity-hub:kind-smoke"
ns=maity
work="$(mktemp -d)"
export KUBECONFIG="$work/kubeconfig"
forward_pid=""

cleanup() {
    [ -n "$forward_pid" ] && kill "$forward_pid" 2>/dev/null || true
    kind delete cluster --name "$name" --kubeconfig "$KUBECONFIG" >/dev/null 2>&1 || true
    rm -rf "$work"
}
trap cleanup EXIT

step() { printf '\n== %s\n' "$1"; }
secret() { python3 -c 'import secrets; print(secrets.token_hex(16))'; }
hub_pods() { kubectl -n "$ns" get pods -l app.kubernetes.io/name=maity-hub,app.kubernetes.io/component=hub -o name; }

# A pod in namespace $1 that asks the hub's health once; prints Succeeded or Failed.
reach() {
    kubectl get namespace "$1" >/dev/null 2>&1 || kubectl create namespace "$1" >/dev/null
    kubectl -n "$1" apply -f - >/dev/null <<YAML
apiVersion: v1
kind: Pod
metadata: {name: reach}
spec:
  restartPolicy: Never
  securityContext: {runAsNonRoot: true, runAsUser: 10001, seccompProfile: {type: RuntimeDefault}}
  containers:
    - name: reach
      image: $image
      imagePullPolicy: Never
      command: [python, -c, "import urllib.request; urllib.request.urlopen('http://hub-maity-hub.$ns/api/v1/health', timeout=5)"]
      securityContext: {allowPrivilegeEscalation: false, capabilities: {drop: [ALL]}}
YAML
    local phase=""
    for _ in $(seq 60); do
        phase="$(kubectl -n "$1" get pod reach -o jsonpath='{.status.phase}')"
        case "$phase" in Succeeded | Failed) break ;; esac
        sleep 1
    done
    kubectl -n "$1" delete pod reach --wait=false >/dev/null
    echo "$phase"
}

step "cluster $name, the hub image, PostgreSQL"
kind create cluster --name "$name" --kubeconfig "$KUBECONFIG" --wait 120s
docker build -q -f "$root/deploy/Dockerfile" -t "$image" "$root"
kind load docker-image "$image" --name "$name"
kubectl create namespace "$ns"
db_password="$(secret)"
kubectl -n "$ns" create secret generic postgres --from-literal=password="$db_password"
kubectl -n "$ns" apply -f - <<'EOF'
apiVersion: apps/v1
kind: Deployment
metadata: {name: postgres}
spec:
  selector: {matchLabels: {app: postgres}}
  template:
    metadata: {labels: {app: postgres}}
    spec:
      containers:
        - name: postgres
          image: postgres:17
          env:
            - {name: POSTGRES_USER, value: maity}
            - {name: POSTGRES_DB, value: maity}
            - name: POSTGRES_PASSWORD
              valueFrom: {secretKeyRef: {name: postgres, key: password}}
          readinessProbe:
            exec: {command: [pg_isready, -U, maity, -d, maity]}
            periodSeconds: 2
---
apiVersion: v1
kind: Service
metadata: {name: postgres}
spec:
  selector: {app: postgres}
  ports: [{port: 5432}]
EOF
kubectl -n "$ns" rollout status deploy/postgres --timeout=180s
# The URL goes into the Secret from a file, never through the command line.
(umask 077; printf 'postgresql://maity:%s@postgres:5432/maity' "$db_password" >"$work/database-url")
kubectl -n "$ns" create secret generic maity-hub-database --from-file=database-url="$work/database-url"

values=(--set image.repository=maity-hub --set image.tag=kind-smoke --set image.pullPolicy=Never
    --set database.existingSecret=maity-hub-database --set config.publicUrl=https://maity.test)

step "install: the migrate Job runs first, then the hub turns ready"
helm install hub "$chart" -n "$ns" "${values[@]}" --wait --timeout 10m
kubectl -n "$ns" logs job/hub-maity-hub-migrate | tee "$work/migrate.log"
grep -q "schema empty -> " "$work/migrate.log"
helm test hub -n "$ns" --logs

step "the NetworkPolicy: the ingress controller's namespace reaches the hub, another one does not"
allowed="$(reach ingress-nginx)"
other="$(reach elsewhere)"
echo "from ingress-nginx: $allowed, from elsewhere: $other"
[ "$allowed" = Succeeded ] && [ "$other" = Failed ]

step "a human account through kubectl exec, a login through a port-forward"
owner_password="$(secret)"
printf '%s\n' "$owner_password" | kubectl -n "$ns" exec -i deploy/hub-maity-hub -- \
    maity-hub owner create --handle owner --display-name Owner
kubectl -n "$ns" port-forward svc/hub-maity-hub 18975:80 >"$work/forward.log" 2>&1 &
forward_pid=$!
for _ in $(seq 50); do curl -sf http://127.0.0.1:18975/api/v1/health >/dev/null && break; sleep 0.2; done
curl -sS --fail http://127.0.0.1:18975/api/v1/health
echo
printf '{"handle":"owner","password":"%s"}' "$owner_password" >"$work/login.json"
curl -sS --fail -o /dev/null -c "$work/jar" -H 'Content-Type: application/json' \
    -d @"$work/login.json" http://127.0.0.1:18975/api/v1/auth/login
curl -sS --fail -b "$work/jar" http://127.0.0.1:18975/api/v1/auth/session \
    | python3 -c 'import json,sys; d=json.load(sys.stdin); print("logged in as", d["member"]["handle"])'
kill "$forward_pid"; forward_pid=""

step "upgrade: the migration runs again, the new pod replaces the old one"
before="$(hub_pods)"
helm upgrade hub "$chart" -n "$ns" "${values[@]}" --set podAnnotations.smoke=upgraded --wait --timeout 10m
kubectl -n "$ns" logs job/hub-maity-hub-migrate | tee "$work/migrate.log"
grep -q "schema .* -> " "$work/migrate.log"
after="$(hub_pods)"
[ "$(wc -l <<<"$after")" = 1 ] && [ "$after" != "$before" ]
echo "one hub pod, a new one: $after"
helm test hub -n "$ns"

step "a migration that fails stops the upgrade; the running hub stays"
printf 'postgresql://maity:wrong@postgres:5432/maity' >"$work/broken-url"
kubectl -n "$ns" create secret generic maity-hub-broken --from-file=database-url="$work/broken-url"
if helm upgrade hub "$chart" -n "$ns" "${values[@]}" --set database.existingSecret=maity-hub-broken \
    --set migrate.backoffLimit=0 --wait --timeout 10m; then
    echo "kind smoke: an upgrade with a failing migration went through" >&2
    exit 1
fi
kubectl -n "$ns" logs job/hub-maity-hub-migrate 2>&1 | tail -1
[ "$(hub_pods)" = "$after" ]
kubectl -n "$ns" get deploy/hub-maity-hub -o jsonpath='{.status.readyReplicas}' | grep -qx 1
helm test hub -n "$ns"

printf '\nkind smoke: install, test, login, upgrade and a refused upgrade all held\n'
