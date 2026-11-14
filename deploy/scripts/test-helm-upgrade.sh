#!/bin/bash
# Runs helm-upgrade.sh against stub kubectl/helm binaries and checks each failure path:
# the exit status, whether Helm was started, and the replicas the Deployment ends with.
# Usage: deploy/scripts/test-helm-upgrade.sh   (no cluster needed)
set -u
here=$(cd "$(dirname "$0")" && pwd)
work=$(mktemp -d); trap 'rm -rf "$work"' EXIT
mkdir -p "$work/bin"

cat > "$work/bin/kubectl" <<'STUB'
#!/bin/bash
# state: $S/replicas (current), $S/pods (names, one per line), $S/log (calls); $FAIL names the failing step
S=$STUB_STATE
echo "kubectl $*" >> "$S/log"
case "$*" in
  *"get deploy"*)           cat "$S/replicas"; exit 0;;
  *"get cronjob/"*)         [ "$FAIL" = no_cronjob ] && { echo "Error from server (NotFound)" >&2; exit 1; }; echo "${*##* get }"; exit 0;;
  *"create job"*)           [ "$FAIL" = dump ] && exit 1; exit 0;;
  *'type=="Complete"'*)     [ "$FAIL" = job_failed ] && exit 0; echo True; exit 0;;
  *'type=="Failed"'*)       [ "$FAIL" = job_failed ] && echo True; exit 0;;
  *"get pod -l"*)           [ "$FAIL" = no_dump_pod ] && exit 0; echo pod/dump-1; exit 0;;
  *"logs"*)
    [ "$FAIL" = logs_unreadable ] && { echo "error: pod gone" >&2; exit 1; }
    [ "$FAIL" = dump_retry ] && echo "pg_dump: error: connection to server failed: Connection refused"
    if [ "$FAIL" = dump_notar ]; then echo "dump ok: /backups/maity-20261029T000000Z.dump.gpg 4048709"
    elif [ "$FAIL" != dump_nomark ]; then echo "dump ok: /backups/maity-20261029T000000Z.dump.gpg 4048709 attachments 10402 (encrypted; plain bytes: dump 4048541, attachments 10240)"; fi
    exit 0;;
  *"delete job"*)           exit 0;;
  *"scale"*)
    all="$*"; n=${all##*--replicas=}
    if [ "$n" = 0 ]; then
      [ "$FAIL" = scale_down ] && exit 1
      echo 0 > "$S/replicas"; [ "$FAIL" = pods_stay ] || : > "$S/pods"; exit 0
    fi
    [ "$FAIL" = restore ] && exit 1
    echo "$n" > "$S/replicas"; exit 0;;
  *"get pods"*)             [ "$FAIL" = list ] && exit 1; cat "$S/pods"; exit 0;;
  *"rollout status"*)       [ "$FAIL" = rollout ] && exit 1; exit 0;;
esac
exit 0
STUB
cat > "$work/bin/helm" <<'STUB'
#!/bin/bash
# The rendering before anything changes (--dry-run) is logged apart: "helm ran" means the upgrade itself.
case " $* " in
  *" --dry-run "*|*" --dry-run=client "*)
    echo "helm-dry $*" >> "$STUB_STATE/log"
    [ "$FAIL" = render ] && exit 1
    # MANIFEST_FILE: a test's own rendering, printed as it is.
    [ -n "${MANIFEST_FILE:-}" ] && { cat "$MANIFEST_FILE"; exit 0; }
    printf 'HOOKS:\n          image: "%s"\n' "${HOOK_REF:-${IMAGE_REF:-$DIGEST_REF}}"
    printf 'MANIFEST:\n    spec:\n      containers:\n        - name: hub\n          image: %s\n' "${IMAGE_REF:-$DIGEST_REF}"
    exit 0;;
esac
echo "helm $*" >> "$STUB_STATE/log"
[ "$FAIL" = helm ] && exit 7
# Helm resets the scaled Deployment to the count the release renders, when the test names one.
[ -n "${RENDERED:-}" ] && echo "$RENDERED" > "$STUB_STATE/replicas"
exit 0
STUB
cat > "$work/bin/cosign" <<'STUB'
#!/bin/bash
echo "cosign $*" >> "$STUB_STATE/log"
[ "$FAIL" = unsigned ] && { echo "error: no matching signatures" >&2; exit 1; }
# UNSIGNED_REF: only this one image fails the check.
[ -n "${UNSIGNED_REF:-}" ] && [ "$2" = "$UNSIGNED_REF" ] && { echo "error: no matching signatures" >&2; exit 1; }
exit 0
STUB
cat > "$work/bin/sleep" <<'STUB'
#!/bin/bash
exit 0
STUB
chmod +x "$work/bin/"*
unset NO_SIGNATURE_CHECK IMAGE_REF HOOK_REF UNSIGNED_REF MANIFEST_FILE
export COSIGN="$work/bin/cosign"
DIGEST_REF="ghcr.io/oliver-zehentleitner/maity-hub@sha256:$(printf 'a%.0s' {1..64})"
export DIGEST_REF

failures=0
run() { # name, FAIL value, initial replicas, expected exit, expect helm (yes/no), expected final replicas, [pods left], [max seconds]
  local name=$1 fail=$2 initial=$3 want=$4 helm=$5 final=$6 podsleft=${7:-} maxsecs=${8:-} dumptimeout=${9:-20}
  export STUB_STATE="$work/$name"; mkdir -p "$STUB_STATE"
  echo "$initial" > "$STUB_STATE/initial"; echo "$initial" > "$STUB_STATE/replicas"
  echo pod/hub-1 > "$STUB_STATE/pods"; : > "$STUB_STATE/log"
  [ "$initial" = 0 ] && [ "$podsleft" != yes ] && : > "$STUB_STATE/pods"
  local t0=$SECONDS
  # CJ names the CronJob (dump unless set; CJ=default leaves DUMP_CRONJOB unset), NO_DUMP is passed as given.
  local cj=${CJ:-dump}; [ "$cj" = default ] && cj=""
  # EXTRA: more caller arguments after -f values.yaml, split on spaces.
  local extra=(); read -ra extra <<<"${EXTRA:-}"
  PATH="$work/bin:$PATH" FAIL=$fail STOP_TIMEOUT=4 DUMP_TIMEOUT=$dumptimeout DUMP_REQUIRES_ATTACHMENTS=${REQ_ATT:-0} DUMP_CRONJOB=$cj \
    NO_DUMP=${NO_DUMP:-} "$here/helm-upgrade.sh" -f values.yaml "${extra[@]}" >"$STUB_STATE/out" 2>&1
  local got=$? ran=no took=$((SECONDS - t0)); grep -q '^helm ' "$STUB_STATE/log" && ran=yes
  local end; end=$(cat "$STUB_STATE/replicas")
  if [ -n "$maxsecs" ] && [ "$took" -gt "$maxsecs" ]; then
    echo "FAIL $name: took $took s, more than $maxsecs s (it must not wait out the timeout)"; failures=$((failures + 1)); return
  fi
  # UNTOUCHED=1: the script must stop before the CronJob probe, the dump, the migrate Job and any scaling.
  if [ "${UNTOUCHED:-}" = 1 ] && grep -qE '^kubectl .*(get cronjob|create job|delete job|scale)' "$STUB_STATE/log"; then
    echo "FAIL $name: it changed the cluster before stopping"; failures=$((failures + 1)); return
  fi
  if [ "$got" = "$want" ] && [ "$ran" = "$helm" ] && [ "$end" = "$final" ]; then
    echo "ok   $name (exit $got, helm $ran, replicas $end${maxsecs:+, ${took} s})"
  else
    echo "FAIL $name: exit $got (want $want), helm $ran (want $helm), replicas $end (want $final)"; failures=$((failures + 1))
  fi
}

run all_good   none       1 0 yes 1
run dump       dump       1 1 no  1
run job_failed job_failed 1 1 no  1 "" 5
run bad_timeout none 1 1 no  1 "" "" 5m
run dump_notar_ok dump_notar 1 0 yes 1
REQ_ATT=1 run dump_notar_required dump_notar 1 1 no  1
REQ_ATT=1 run dump_tar_required_ok none 1 0 yes 1
run dump_nomark dump_nomark 1 1 no  1
run dump_retry dump_retry 1 0 yes 1
run logs_unreadable logs_unreadable 1 1 no  1
run no_dump_pod no_dump_pod 1 1 no  1
run scale_down scale_down 1 1 no  1
run pods_stay  pods_stay  1 1 no  1
run list       list       1 1 no  1
run helm       helm       1 7 yes 1
run restore    restore    1 3 yes 0
run rollout    rollout    1 4 yes 1
run initial0   none       0 0 yes 0
run initial0_pods none    0 1 no  0 yes
# A changed `replicas`: the count the release renders stays after a successful upgrade.
RENDERED=3 run more_replicas none 1 0 yes 3
RENDERED=1 run fewer_replicas none 3 0 yes 1
RENDERED=3 run helm_fails_keeps_old helm 1 7 yes 1
RENDERED=2 run initial0_rendered none 0 0 yes 0
# Helm succeeded, the rollout check then fails: the rendered count stays (the release's), exit 4.
RENDERED=3 run rollout_rendered rollout 1 4 yes 3
# A dump is taken by default: an unset DUMP_CRONJOB means maity-pg-dump, NO_DUMP=1 is the only way to skip it.
logged() { # name, text the stub log must (yes) or must not (no) contain
  if grep -qF -- "$3" "$work/$1/log"; then [ "$2" = yes ]; else [ "$2" = no ]; fi && echo "ok   $1: the log $([ "$2" = yes ] && echo has || echo "has no") '$3'" \
    || { echo "FAIL $1: expected the log to be $2 on '$3'"; failures=$((failures + 1)); }
}
CJ=default run default_cronjob none 1 0 yes 1
logged default_cronjob yes "create job --from=cronjob/maity-pg-dump"
CJ=default run default_cronjob_missing no_cronjob 1 1 no 1
logged default_cronjob_missing no "create job"
NO_DUMP=1 run no_dump no_cronjob 1 0 yes 1
logged no_dump no "create job"
logged no_dump no "get cronjob"
NO_DUMP=yes run no_dump_bad none 1 1 no 1
logged no_dump_bad no "create job"
NO_DUMP=0 run no_dump_zero none 1 0 yes 1
logged no_dump_zero yes "create job --from=cronjob/dump"
# The image's signature, checked before anything changes; NO_SIGNATURE_CHECK=1 is the only way past it.
if grep -qF -- "cosign verify $DIGEST_REF --certificate-oidc-issuer https://token.actions.githubusercontent.com --certificate-identity-regexp ^https://" "$work/all_good/log"; then
  echo "ok   signature_checked (the digest, with the issuer and the identity)"
else
  echo "FAIL signature_checked: no cosign verify of $DIGEST_REF in the log"; failures=$((failures + 1))
fi
UNTOUCHED=1 run unsigned unsigned 1 1 no 1
UNTOUCHED=1 run render_fails render 1 1 no 1
UNTOUCHED=1 IMAGE_REF=ghcr.io/oliver-zehentleitner/maity-hub:0.1.0a2 run tag_not_digest none 1 1 no 1
UNTOUCHED=1 COSIGN=no-such-cosign run cosign_missing none 1 1 no 1
NO_SIGNATURE_CHECK=1 COSIGN=no-such-cosign run opt_out_without_cosign none 1 0 yes 1
NO_SIGNATURE_CHECK=1 IMAGE_REF=registry.example.org/maity-hub:mine run opt_out_tag none 1 0 yes 1
grep -q '^cosign ' "$work/opt_out_tag/log" && { echo "FAIL opt_out_tag: cosign ran with NO_SIGNATURE_CHECK=1"; failures=$((failures + 1)); }
# NO_SIGNATURE_CHECK=1 says so; any other value runs the normal check.
grep -q '^WARNING: NO_SIGNATURE_CHECK=1' "$work/opt_out_tag/out" || { echo "FAIL opt_out_tag: no WARNING for NO_SIGNATURE_CHECK=1"; failures=$((failures + 1)); }
UNTOUCHED=1 NO_SIGNATURE_CHECK=0 run opt_out_zero_checks unsigned 1 1 no 1
grep -q '^cosign verify ' "$work/opt_out_zero_checks/log" || { echo "FAIL opt_out_zero_checks: cosign did not run with NO_SIGNATURE_CHECK=0"; failures=$((failures + 1)); }
# The rendering gets the caller's own arguments, between two --dry-run=client (Helm takes the last one).
if grep -qE '^helm-dry -n maity upgrade maity [^ ]+ --dry-run=client -f values\.yaml --dry-run=client$' "$work/all_good/log"; then
  echo "ok   dry_run_has_caller_args"
else
  echo "FAIL dry_run_has_caller_args: no helm --dry-run=client -f values.yaml --dry-run=client in the log"; failures=$((failures + 1))
fi
# A --dry-run among the caller's arguments would win over the script's (the last one counts) and make the
# rendering the real upgrade: every spelling is refused with exit 2 before kubectl, helm or cosign runs.
dry_case() { # name, the caller's extra arguments
  EXTRA=$2 run "dry_$1" none 1 2 no 1
  [ -s "$work/dry_$1/log" ] && { echo "FAIL dry_$1: something ran before the refusal: $(head -1 "$work/dry_$1/log")"; failures=$((failures + 1)); }
  grep -q 'takes no --dry-run' "$work/dry_$1/out" || { echo "FAIL dry_$1: no message naming --dry-run"; failures=$((failures + 1)); }
}
dry_case false "--install --dry-run=false"
dry_case server "--dry-run=server"
dry_case bare "--dry-run"
dry_case spaced "--dry-run false"
dry_case after_set "--set image.tag=x --dry-run=none"
NO_SIGNATURE_CHECK=1 dry_case opt_out "--dry-run=false"
# Two distinct images (the hook's and the Deployment's): each is checked, and the hook's failing stops it.
hook_ref="ghcr.io/oliver-zehentleitner/maity-hub@sha256:$(printf 'b%.0s' {1..64})"
HOOK_REF=$hook_ref run two_refs none 1 0 yes 1
for r in "$DIGEST_REF" "$hook_ref"; do
  grep -qF -- "cosign verify $r " "$work/two_refs/log" || { echo "FAIL two_refs: $r was not checked"; failures=$((failures + 1)); }
done
UNTOUCHED=1 HOOK_REF=$hook_ref UNSIGNED_REF=$hook_ref run hook_unsigned none 1 1 no 1
grep -qF "$hook_ref has no valid signature" "$work/hook_unsigned/out" || { echo "FAIL hook_unsigned: no message naming the hook's image"; failures=$((failures + 1)); }
# Every form an image takes in the rendering: a list-item sidecar, an init container, quoted keys and values,
# a trailing comment; empty entries are skipped.
init_ref="ghcr.io/example/init@sha256:$(printf 'c%.0s' {1..64})"
side_ref="ghcr.io/example/sidecar@sha256:$(printf 'd%.0s' {1..64})"
quoted_ref="ghcr.io/example/quoted@sha256:$(printf 'e%.0s' {1..64})"
cat > "$work/forms.yaml" <<EOF
MANIFEST:
    spec:
      initContainers:
        - image: $init_ref
          name: init
      containers:
        - name: hub
          image: "$DIGEST_REF"  # the hub
        - image: '$side_ref'
          name: sidecar
        - name: quoted
          "image": $quoted_ref
        - name: empty
          image: ""
        - name: none
          image:
          imagePullPolicy: IfNotPresent
EOF
MANIFEST_FILE="$work/forms.yaml" run image_forms none 1 0 yes 1
for r in "$DIGEST_REF" "$init_ref" "$side_ref" "$quoted_ref"; do
  grep -qF -- "cosign verify $r " "$work/image_forms/log" || { echo "FAIL image_forms: $r was not checked"; failures=$((failures + 1)); }
done
[ "$(grep -c '^cosign verify ' "$work/image_forms/log")" = 4 ] || { echo "FAIL image_forms: not exactly the four images were checked"; failures=$((failures + 1)); }
grep -q '^signature checked: *$' "$work/image_forms/out" && { echo "FAIL image_forms: an empty image name was printed"; failures=$((failures + 1)); }
UNTOUCHED=1 MANIFEST_FILE="$work/forms.yaml" UNSIGNED_REF=$side_ref run sidecar_unsigned none 1 1 no 1
# Every runnable image in every workload kind, the key order mixed: the image first or after the name,
# in containers, initContainers and ephemeralContainers, in hook Jobs and Pods (helm.sh/hook) too.
wl() { printf 'ghcr.io/example/%s@sha256:%s' "$1" "$(printf '%064d' 0 | tr 0 "$2")"; }
w_dep=$(wl dep-init 1); w_sts=$(wl sts-side 2); w_job=$(wl hook-job 3); w_jobi=$(wl hook-job-init 4)
w_cron=$(wl cron 5); w_pod=$(wl hook-pod 6); w_eph=$(wl ephemeral 7); w_ds=$(wl ds-init 8)
cat > "$work/workloads.yaml" <<WORKLOADS
HOOKS:
---
apiVersion: batch/v1
kind: Job
metadata:
  name: migrate
  annotations:
    "helm.sh/hook": pre-upgrade
spec:
  template:
    spec:
      initContainers:
      - image: $w_jobi
        name: wait
      containers:
      - image: "$w_job"
        name: migrate
---
apiVersion: v1
kind: Pod
metadata:
  name: hook-test
  annotations:
    helm.sh/hook: test
spec:
  containers:
    - name: test
      image: $w_pod
MANIFEST:
---
apiVersion: apps/v1
kind: Deployment
spec:
  template:
    spec:
      initContainers:
        - image: $w_dep
          name: init
      containers:
        - name: hub
          image: $DIGEST_REF
---
apiVersion: apps/v1
kind: StatefulSet
spec:
  template:
    spec:
      containers:
        - name: hub
          image: $DIGEST_REF
        - image: $w_sts
          name: side
---
apiVersion: apps/v1
kind: DaemonSet
spec:
  template:
    spec:
      initContainers:
        - name: init
          image: '$w_ds'
      containers:
        - image: $DIGEST_REF
          name: hub
---
apiVersion: batch/v1
kind: CronJob
spec:
  jobTemplate:
    spec:
      template:
        spec:
          containers:
          - image: $w_cron
            imagePullPolicy: IfNotPresent
            name: dump
---
apiVersion: v1
kind: Pod
spec:
  containers:
    - name: hub
      image: $DIGEST_REF
  ephemeralContainers:
    - image: $w_eph
      name: debug
WORKLOADS
MANIFEST_FILE="$work/workloads.yaml" run workloads none 1 0 yes 1
for r in "$DIGEST_REF" "$w_dep" "$w_sts" "$w_job" "$w_jobi" "$w_cron" "$w_pod" "$w_eph" "$w_ds"; do
  grep -qF -- "cosign verify $r " "$work/workloads/log" || { echo "FAIL workloads: $r was not checked"; failures=$((failures + 1)); }
done
[ "$(grep -c '^cosign verify ' "$work/workloads/log")" = 9 ] || { echo "FAIL workloads: not exactly the nine images were checked"; failures=$((failures + 1)); }
# Any one of them unsigned stops the upgrade before anything changes.
for r in "$w_dep" "$w_sts" "$w_job" "$w_jobi" "$w_cron" "$w_pod" "$w_eph" "$w_ds"; do
  n=${r#ghcr.io/example/}; n=${n%%@*}
  UNTOUCHED=1 MANIFEST_FILE="$work/workloads.yaml" UNSIGNED_REF=$r run "workload_unsigned_$n" none 1 1 no 1
done
# A signed hub (name first) beside an init container and a sidecar by tag, image first; and the same two
# with the name first. Both spellings stop at the tag before anything changes.
untrusted=registry.example.org/untrusted:latest
cat > "$work/tag-image-first.yaml" <<TAGS
MANIFEST:
    spec:
      initContainers:
        - image: $untrusted
          name: init
      containers:
        - name: hub
          image: $DIGEST_REF
        - image: $untrusted
          name: side
TAGS
cat > "$work/tag-name-first.yaml" <<TAGS
MANIFEST:
    spec:
      initContainers:
        - name: init
          image: $untrusted
      containers:
        - name: hub
          image: $DIGEST_REF
        - name: side
          image: $untrusted
TAGS
for order in image-first name-first; do
  UNTOUCHED=1 MANIFEST_FILE="$work/tag-$order.yaml" run "tag_$order" none 1 1 no 1
  grep -qF "$untrusted is not pinned by digest" "$work/tag_$order/out" || { echo "FAIL tag_$order: the tag was not named"; failures=$((failures + 1)); }
done
# A form the check does not read stops the script before anything changes (fail closed).
form_case() { # name, the line(s) after "containers:"
  printf 'MANIFEST:\n    spec:\n      containers:\n%s\n' "$2" > "$work/form-$1.yaml"
  UNTOUCHED=1 MANIFEST_FILE="$work/form-$1.yaml" run "form_$1" none 1 1 no 1
  grep -q 'form the check does not read' "$work/form_$1/out" || { echo "FAIL form_$1: not refused as an unread form"; failures=$((failures + 1)); }
}
form_case flow_mapping "        - {name: side, image: $side_ref}"
form_case flow_list_item "        - name: hub
          resources: {image: $side_ref}"
form_case block_scalar "        - name: side
          image: >-
            $side_ref"
form_case plain_continued "        - name: side
          image:
            $side_ref"
form_case anchor "        - name: side
          image: &img $side_ref"
form_case alias "        - name: side
          image: *img"
# Real Helm parses the flags: the script's rendering against a loopback stand-in for the Kubernetes API
# that answers reads and refuses every write. With the caller's --install it renders with no write and
# reaches cosign; a caller's --dry-run=false is refused before Helm runs. The control shows that the same
# Helm makes a write when --dry-run=false comes last, so "no write" above is not a quiet stand-in.
# REAL_HELM names a Helm 3 binary; without one (or without python3) this part is skipped.
real_helm=${REAL_HELM:-$(command -v helm || true)}
if [ -z "$real_helm" ] || ! "$real_helm" version --short 2>/dev/null | grep -q '^v3\.' || ! command -v python3 >/dev/null; then
  echo "skip real_helm: no Helm 3 binary (REAL_HELM or helm on PATH) or no python3; the stub cases above still run"
else
  cat > "$work/fakeapi.py" <<'FAKEAPI'
import json, sys
from http.server import BaseHTTPRequestHandler, HTTPServer
log = open(sys.argv[1], "a", buffering=1)
V1 = [{"name": n, "namespaced": True, "kind": k, "verbs": ["get", "list", "create"]}
      for n, k in (("pods", "Pod"), ("secrets", "Secret"), ("configmaps", "ConfigMap"))]
class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass
    def send(self, code, body):
        b = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)
    def do_GET(self):
        log.write("GET " + self.path + "\n")
        p = self.path.split("?")[0]
        if p == "/version":
            return self.send(200, {"major": "1", "minor": "31", "gitVersion": "v1.31.0"})
        if p == "/api":
            return self.send(200, {"kind": "APIVersions", "versions": ["v1"]})
        if p == "/apis":
            return self.send(200, {"kind": "APIGroupList", "groups": []})
        if p == "/api/v1":
            return self.send(200, {"kind": "APIResourceList", "groupVersion": "v1", "resources": V1})
        if p.endswith("/secrets") or p.endswith("/configmaps"):
            return self.send(200, {"kind": "List", "apiVersion": "v1", "metadata": {}, "items": []})
        return self.send(404, {"kind": "Status", "status": "Failure", "reason": "NotFound", "code": 404})
    def refuse(self):
        log.write(self.command + " " + self.path + "\n")
        self.send(403, {"kind": "Status", "status": "Failure", "reason": "Forbidden", "code": 403, "message": "writes refused"})
    do_POST = do_PUT = do_PATCH = do_DELETE = refuse
srv = HTTPServer(("127.0.0.1", 0), H)
with open(sys.argv[2], "w") as f:
    f.write(str(srv.server_port))
srv.serve_forever()
FAKEAPI
  rh=$work/realhelm; mkdir -p "$rh/bin" "$rh/chart/templates" "$rh/home"
  printf 'apiVersion: v2\nname: probe\nversion: 0.1.0\n' > "$rh/chart/Chart.yaml"
  printf 'apiVersion: v1\nkind: Pod\nmetadata:\n  name: probe\nspec:\n  containers:\n    - name: hub\n      image: %s\n' "$DIGEST_REF" > "$rh/chart/templates/pod.yaml"
  : > "$rh/requests"
  python3 -I "$work/fakeapi.py" "$rh/requests" "$rh/port" & api_pid=$!
  trap 'kill "$api_pid" 2>/dev/null; rm -rf "$work"' EXIT
  for _ in $(seq 50); do [ -s "$rh/port" ] && break; sleep 0.1; done
  printf 'apiVersion: v1\nkind: Config\nclusters: [{name: fake, cluster: {server: "http://127.0.0.1:%s"}}]\nusers: [{name: fake, user: {token: none}}]\ncontexts: [{name: fake, context: {cluster: fake, user: fake, namespace: maity}}]\ncurrent-context: fake\n' \
    "$(cat "$rh/port")" > "$rh/kubeconfig"
  # Real helm; kubectl, cosign and sleep stay the stubs.
  ln -s "$real_helm" "$rh/bin/helm"; ln -s "$work/bin/kubectl" "$work/bin/cosign" "$work/bin/sleep" "$rh/bin/"
  writes() { grep -cv '^GET ' "$rh/requests"; }
  real_run() { # name, expected exit, then the caller's arguments after -f values.yaml
    local name=$1 want=$2; shift 2
    export STUB_STATE="$work/$name"; mkdir -p "$STUB_STATE"; echo 1 > "$STUB_STATE/replicas"; : > "$STUB_STATE/pods"; : > "$STUB_STATE/log"
    : > "$rh/requests"; printf 'replicaCount: 1\n' > "$rh/values.yaml"
    # cosign refuses (FAIL=unsigned): the run ends at the first signature check, after the rendering.
    PATH="$rh/bin:$PATH" KUBECONFIG="$rh/kubeconfig" HELM_CACHE_HOME="$rh/home/cache" HELM_CONFIG_HOME="$rh/home/config" \
      HELM_DATA_HOME="$rh/home/data" CHART="$rh/chart" FAIL=unsigned STOP_TIMEOUT=4 DUMP_CRONJOB=dump \
      "$here/helm-upgrade.sh" -f "$rh/values.yaml" "$@" >"$STUB_STATE/out" 2>&1
    local got=$? w; w=$(writes)
    if [ "$got" = "$want" ] && [ "$w" = 0 ]; then echo "ok   $name (real helm: exit $got, no write to the API)"
    else echo "FAIL $name: exit $got (want $want), $w write(s) to the API: $(grep -v '^GET ' "$rh/requests" | head -1)"; failures=$((failures + 1)); fi
  }
  real_run real_helm_renders 1 --install --disable-openapi-validation
  grep -qF "cosign verify $DIGEST_REF " "$work/real_helm_renders/log" || { echo "FAIL real_helm_renders: the rendering did not reach the signature check"; failures=$((failures + 1)); }
  real_run real_helm_dry_run_false 2 --install --disable-openapi-validation --dry-run=false
  grep -q '^cosign ' "$work/real_helm_dry_run_false/log" && { echo "FAIL real_helm_dry_run_false: cosign ran"; failures=$((failures + 1)); }
  # Control: Helm takes the last --dry-run, and the stand-in sees the write it makes.
  : > "$rh/requests"
  KUBECONFIG="$rh/kubeconfig" HELM_CACHE_HOME="$rh/home/cache" HELM_CONFIG_HOME="$rh/home/config" HELM_DATA_HOME="$rh/home/data" \
    "$real_helm" -n maity upgrade maity "$rh/chart" --dry-run=client --install --disable-openapi-validation --dry-run=false >/dev/null 2>&1
  if [ "$(writes)" -ge 1 ]; then echo "ok   real_helm_control (a later --dry-run=false wins and writes)"
  else echo "FAIL real_helm_control: no write seen with --dry-run=false last, so the API stand-in proves nothing"; failures=$((failures + 1)); fi
  kill "$api_pid" 2>/dev/null
fi
# The identity the script checks is the one the install docs name.
identity=$(sed -n "s/^IDENTITY='\(.*\)'\$/\1/p" "$here/helm-upgrade.sh")
issuer=$(sed -n "s/^ISSUER='\(.*\)'\$/\1/p" "$here/helm-upgrade.sh")
readme="$here/../helm/maity-hub/README.md"
if [ -n "$identity" ] && grep -qF -- "--certificate-identity-regexp '$identity'" "$readme"; then
  echo "ok   identity_matches_readme"
else
  echo "FAIL identity_matches_readme: the script's IDENTITY is not the README's --certificate-identity-regexp"; failures=$((failures + 1))
fi
if [ -n "$issuer" ] && grep -qE -- "--certificate-oidc-issuer '?$(printf '%s' "$issuer" | sed 's/[.]/\\./g')'?( |\\|\$)" "$readme"; then
  echo "ok   issuer_matches_readme"
else
  echo "FAIL issuer_matches_readme: the script's ISSUER is not the README's --certificate-oidc-issuer"; failures=$((failures + 1))
fi
[ "$failures" = 0 ] && echo "all scenarios pass" || { echo "$failures scenario(s) failed"; exit 1; }
