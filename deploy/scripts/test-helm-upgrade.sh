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
  *" --dry-run "*)
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
export DIGEST_REF="ghcr.io/oliver-zehentleitner/maity-hub@sha256:$(printf 'a%.0s' {1..64})"

failures=0
run() { # name, FAIL value, initial replicas, expected exit, expect helm (yes/no), expected final replicas, [pods left], [max seconds]
  local name=$1 fail=$2 initial=$3 want=$4 helm=$5 final=$6 podsleft=${7:-} maxsecs=${8:-} dumptimeout=${9:-20}
  export STUB_STATE="$work/$name"; mkdir -p "$STUB_STATE"
  echo "$initial" > "$STUB_STATE/initial"; echo "$initial" > "$STUB_STATE/replicas"
  echo pod/hub-1 > "$STUB_STATE/pods"; : > "$STUB_STATE/log"
  [ "$initial" = 0 ] && [ "$podsleft" != yes ] && : > "$STUB_STATE/pods"
  local t0=$SECONDS
  PATH="$work/bin:$PATH" FAIL=$fail STOP_TIMEOUT=4 DUMP_TIMEOUT=$dumptimeout DUMP_REQUIRES_ATTACHMENTS=${REQ_ATT:-0} DUMP_CRONJOB=dump \
    "$here/helm-upgrade.sh" -f values.yaml >"$STUB_STATE/out" 2>&1
  local got=$? ran=no took=$((SECONDS - t0)); grep -q '^helm ' "$STUB_STATE/log" && ran=yes
  local end; end=$(cat "$STUB_STATE/replicas")
  if [ -n "$maxsecs" ] && [ "$took" -gt "$maxsecs" ]; then
    echo "FAIL $name: took $took s, more than $maxsecs s (it must not wait out the timeout)"; failures=$((failures + 1)); return
  fi
  # UNTOUCHED=1: the script must stop before the dump, the migrate Job and any scaling.
  if [ "${UNTOUCHED:-}" = 1 ] && grep -qE '^kubectl .*(create job|delete job|scale)' "$STUB_STATE/log"; then
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
# The rendering gets the caller's own arguments.
if grep -qE '^helm-dry -n maity upgrade maity .* --dry-run -f values\.yaml$' "$work/all_good/log"; then
  echo "ok   dry_run_has_caller_args"
else
  echo "FAIL dry_run_has_caller_args: no helm --dry-run with -f values.yaml in the log"; failures=$((failures + 1))
fi
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
