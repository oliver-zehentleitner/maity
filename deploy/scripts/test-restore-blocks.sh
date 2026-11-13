#!/bin/bash
# Runs the two documented restore blocks (the database's in docs/install/README.md, the attachments' at the top of
# deploy/k3s-single/restore-attachments.yaml) against stub kubectl, gpg and pg_restore, and checks that each one stops
# before anything is restored while the hub is not verifiably stopped: a replica wanted, a pod left, or a kubectl that
# fails. A failure must stop the block even when kubectl prints nothing, which a command substitution inside a test
# does not do under `sh -e`.
# Usage: deploy/scripts/test-restore-blocks.sh   (no cluster needed; GNU tar)
set -u
here=$(cd "$(dirname "$0")" && pwd)
root=$(cd "$here/../.." && pwd)
work=$(mktemp -d); trap 'rm -rf "$work"' EXIT
mkdir -p "$work/bin"

# The block between `sh -eu -c '` and the line that ends it, from a file; the prefix and leading blanks are stripped.
extract() { # file, the line that ends the block, prefix to strip
  awk -v end="$2" -v pre="$3" '
    { line = $0; if (pre != "" && index(line, pre) == 1) line = substr(line, length(pre) + 1); sub(/^[ \t]+/, "", line) }
    inside && index(line, end) == 1 { exit }
    inside { print line }
    index(line, "sh -eu -c '"'"'") == 1 { inside = 1 }
  ' "$1"
}
extract "$root/docs/install/README.md" "' restore <kube context> maity-<UTC time>.dump.gpg" "" > "$work/db-block"
extract "$root/deploy/k3s-single/restore-attachments.yaml" "' restore <kube context>" "#   " > "$work/att-block"
for b in db-block att-block; do
  [ -s "$work/$b" ] || { echo "FAIL could not find the $b in its file"; exit 1; }
  grep -q 'k get pods' "$work/$b" || { echo "FAIL the $b has no pod check"; exit 1; }
done

cat > "$work/bin/kubectl" <<'STUB'
#!/bin/bash
# $FAIL: deploy_fails, pods_fail, replica, pod_left; every call goes to $S/log
echo "kubectl $*" >> "$S/log"
case "$*" in
  *"get deploy"*)  [ "$FAIL" = deploy_fails ] && { echo "error: forbidden" >&2; exit 1; }
                   [ "$FAIL" = replica ] && { printf 1; exit 0; }; printf 0; exit 0;;
  *"get pods"*)    [ "$FAIL" = pods_fail ] && { echo "error: the server is unreachable" >&2; exit 1; }
                   [ "$FAIL" = pod_left ] && echo pod/maity-maity-hub-1; exit 0;;
  *" exec "*)      cat > /dev/null; exit 0;;
esac
exit 0
STUB
cat > "$work/bin/gpg" <<'STUB'
#!/bin/bash
cat "$S/plain"
STUB
cat > "$work/bin/pg_restore" <<'STUB'
#!/bin/bash
exit 0
STUB
chmod +x "$work/bin/"*
mkdir -p "$work/src"; echo file > "$work/src/f"; tar -cf "$work/plain.tar" -C "$work/src" .

failures=0
run() { # block, FAIL value, expected: restores | stops
  local block=$1 fail=$2 want=$3 name="$1/$2"
  export S="$work/run-$block-$fail" FAIL=$fail; mkdir -p "$S"; : > "$S/log"; cp "$work/plain.tar" "$S/plain"
  ( cd "$S" && PATH="$work/bin:$PATH" sh -eu -c "$(cat "$work/$block")" restore test-context backup.gpg ) >"$S/out" 2>&1
  local got=$? reached=stops
  grep -q " exec " "$S/log" && reached=restores
  local status_ok=no
  if [ "$want" = restores ]; then [ "$got" = 0 ] && status_ok=yes; else [ "$got" != 0 ] && status_ok=yes; fi
  if [ "$reached" = "$want" ] && [ "$status_ok" = yes ]; then
    echo "ok   $name ($reached, exit $got)"
  else
    echo "FAIL $name: $reached with exit $got (want $want)"; sed 's/^/     /' "$S/out"; failures=$((failures + 1))
  fi
  # Every kubectl names the context given.
  if grep -v -- "--context test-context" "$S/log" | grep -q .; then echo "FAIL $name: a kubectl without --context"; failures=$((failures + 1)); fi
}
for b in db-block att-block; do
  run $b none restores
  run $b deploy_fails stops
  run $b pods_fail stops
  run $b replica stops
  run $b pod_left stops
done
[ "$failures" = 0 ] && echo "all scenarios pass" || { echo "$failures scenario(s) failed"; exit 1; }
