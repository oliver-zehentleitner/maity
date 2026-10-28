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
  *"get deploy"*)           cat "$S/initial"; exit 0;;
  *"create job"*)           [ "$FAIL" = dump ] && exit 1; exit 0;;
  *"wait --for=condition"*) exit 0;;
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
echo "helm $*" >> "$STUB_STATE/log"
[ "$FAIL" = helm ] && exit 7
exit 0
STUB
cat > "$work/bin/sleep" <<'STUB'
#!/bin/bash
exit 0
STUB
chmod +x "$work/bin/"*

failures=0
run() { # name, FAIL value, initial replicas, expected exit, expect helm (yes/no), expected final replicas, [pods left]
  local name=$1 fail=$2 initial=$3 want=$4 helm=$5 final=$6 podsleft=${7:-}
  export STUB_STATE="$work/$name"; mkdir -p "$STUB_STATE"
  echo "$initial" > "$STUB_STATE/initial"; echo "$initial" > "$STUB_STATE/replicas"
  echo pod/hub-1 > "$STUB_STATE/pods"; : > "$STUB_STATE/log"
  [ "$initial" = 0 ] && [ "$podsleft" != yes ] && : > "$STUB_STATE/pods"
  PATH="$work/bin:$PATH" FAIL=$fail STOP_TIMEOUT=4 DUMP_CRONJOB=dump \
    "$here/helm-upgrade.sh" -f values.yaml >"$STUB_STATE/out" 2>&1
  local got=$? ran=no; grep -q '^helm ' "$STUB_STATE/log" && ran=yes
  local end; end=$(cat "$STUB_STATE/replicas")
  if [ "$got" = "$want" ] && [ "$ran" = "$helm" ] && [ "$end" = "$final" ]; then
    echo "ok   $name (exit $got, helm $ran, replicas $end)"
  else
    echo "FAIL $name: exit $got (want $want), helm $ran (want $helm), replicas $end (want $final)"; failures=$((failures + 1))
  fi
}

run all_good   none       1 0 yes 1
run dump       dump       1 1 no  1
run scale_down scale_down 1 1 no  1
run pods_stay  pods_stay  1 1 no  1
run list       list       1 1 no  1
run helm       helm       1 7 yes 1
run restore    restore    1 3 yes 0
run rollout    rollout    1 4 yes 1
run initial0   none       0 0 yes 0
run initial0_pods none    0 1 no  0 yes
[ "$failures" = 0 ] && echo "all scenarios pass" || { echo "$failures scenario(s) failed"; exit 1; }
