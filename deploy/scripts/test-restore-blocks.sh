#!/bin/bash
# Runs the two documented restore blocks (the database's in docs/install/README.md, the attachments' at the top of
# deploy/k3s-single/restore-attachments.yaml) against stub kubectl, gpg and pg_restore, and checks that each one stops
# before anything is restored while the hub is not verifiably stopped: a replica wanted, a pod left, or a kubectl that
# fails. A failure must stop the block even when kubectl prints nothing, which a command substitution inside a test
# does not do under `sh -e`.
# It also runs the two blocks that close the hub's NetworkPolicy after a restore and open it again (docs/install/README.md,
# steps 4 and 6): the hub starts only once the policy admits nobody, the kept rules are never overwritten, and they are
# removed only once the policy has them again.
# The two restore blocks also check the backup's signature when MAITY_BACKUP_SIGNER names a fingerprint (the signing key's or
# its primary key's), and stop before anything is decrypted when the signature is missing, bad, by another key, or made
# under another file name (the name carries the backup's time stamp), or by a key that is revoked or expired. The same
# blocks run against a real gpg in deploy/scripts/test-backup-signing.sh.
# Usage: deploy/scripts/test-restore-blocks.sh   (no cluster needed; GNU tar, python3)
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
# The close and open blocks (steps 4 and 6): the `sh -eu -c '` block that ends in `' close` and the one in `' open`.
python3 - "$root/docs/install/README.md" "$work" <<'PY'
import re, sys, textwrap
text = open(sys.argv[1]).read()
for name in ("close", "open"):
    m = re.search(r"sh -eu -c '\n(.*?)\n\s*' " + name + r" <kube context>", text, re.S)
    # the block is the last `sh -eu -c '` before the marker; dedented as a whole, so the Python in it keeps its indentation
    body = textwrap.dedent(m.group(1).split("sh -eu -c '\n")[-1]) if m else ""
    open(sys.argv[2] + "/" + name + "-block", "w").write(body + "\n")
PY
for b in db-block att-block close-block open-block; do
  [ -s "$work/$b" ] || { echo "FAIL could not find the $b in its file"; exit 1; }
done
for b in db-block att-block; do
  grep -q 'k get pods' "$work/$b" || { echo "FAIL the $b has no pod check"; exit 1; }
done

cat > "$work/bin/kubectl" <<'STUB'
#!/bin/bash
# $FAIL: deploy_fails, pods_fail, replica, pod_left; every call goes to $S/log
echo "kubectl $*" >> "$S/log"
case "$*" in
  *"get deploy maity-maity-hub -o json")   # the whole Deployment (not -o jsonpath)
                   printf '%s' '{"spec": {"template": {"metadata": {"labels": {"app.kubernetes.io/name": "maity-hub", "app.kubernetes.io/instance": "maity", "app.kubernetes.io/component": "hub"}}}}}'; exit 0;;
  *"get deploy"*)  [ "$FAIL" = deploy_fails ] && { echo "error: forbidden" >&2; exit 1; }
                   [ "$FAIL" = replica ] && { printf 1; exit 0; }; printf 0; exit 0;;
  *"get pods"*)    [ "$FAIL" = pods_fail ] && { echo "error: the server is unreachable" >&2; exit 1; }
                   [ "$FAIL" = pod_left ] && echo pod/maity-maity-hub-1; exit 0;;
  *" exec "*)      cat > /dev/null; exit 0;;
  *"get networkpolicy maity-maity-hub"*)
                   [ "$FAIL" = np_get_fails ] && { echo "error: forbidden" >&2; exit 1; }
                   cat "$S/np.json"; exit 0;;
  *"get networkpolicy"*)   # all of the namespace: the hub's and those in $S/others.json
                   [ "$FAIL" = np_list_fails ] && { echo "error: forbidden" >&2; exit 1; }
                   python3 -c 'import json, sys; print(json.dumps({"items": [json.load(open(sys.argv[1]))] + json.load(open(sys.argv[2]))}))' \
                     "$S/np.json" "$S/others.json"; exit 0;;
  *"patch networkpolicy"*)
                   [ "$FAIL" = patch_fails ] && { echo "error: the server rejected the patch" >&2; exit 1; }
                   [ "$FAIL" = patch_ignored ] && exit 0
                   python3 - "$S/np.json" "$@" <<'PY' || exit 1
import json, sys
path, args = sys.argv[1], sys.argv[2:]
patch = json.loads(args[args.index("-p") + 1])
np = json.load(open(path))
if "--type=json" in args:
    for op in patch:
        assert op["op"] == "replace" and op["path"] == "/spec/ingress"
        np["spec"]["ingress"] = op["value"]
else:
    np["spec"].update(patch["spec"])
if not np["spec"].get("ingress"):
    np["spec"].pop("ingress", None)   # the API server drops an empty list
json.dump(np, open(path, "w"))
PY
                   exit 0;;
esac
exit 0
STUB
cat > "$work/bin/gpg" <<'STUB'
#!/bin/bash
# --verify: $SIG good (by $SUBKEY, primary $PRIMARY, signed under the file's name), renamed (signed under an older name),
# noname (no signed name), double (an older name by the right key, the file's name by another key), revoked or expired (a good signature by a revoked or expired key), other (by another key) or bad; a missing .sig fails like gpg. Else decrypt.
echo "gpg $*" >> "$S/log"
args=("$@")
for i in "${!args[@]}"; do
  [ "${args[$i]}" = --verify ] || continue
  sig=${args[$((i + 1))]} name=$(basename "${args[$((i + 2))]}")
  [ -e "$sig" ] || { echo "gpg: can't open '$sig': No such file or directory" >&2; exit 2; }
  note() { printf '[GNUPG:] NOTATION_NAME backup-file@maity\n[GNUPG:] NOTATION_FLAGS 0 1\n[GNUPG:] NOTATION_DATA %s\n' "$1"; }
  valid="[GNUPG:] VALIDSIG $SUBKEY 2026-11-14 1794614400 0 4 0 22 10 00 $PRIMARY"
  echo "[GNUPG:] NEWSIG"   # gpg opens each signature's section with it
  case "${SIG:-good}" in
    double)  echo "[GNUPG:] GOODSIG ${SUBKEY: -16} sign"; note "maity-20000101T000000Z.dump.gpg"; echo "$valid"
             echo "[GNUPG:] NEWSIG"; echo "[GNUPG:] GOODSIG ${OTHER: -16} other"; note "$name"
             echo "[GNUPG:] VALIDSIG $OTHER 2026-11-14 1794614400 0 4 0 22 10 00 $OTHER"; exit 0;;
    good)    echo "[GNUPG:] GOODSIG ${SUBKEY: -16} sign"; note "$name"; echo "$valid"; exit 0;;
    renamed) echo "[GNUPG:] GOODSIG ${SUBKEY: -16} sign"; note "maity-20000101T000000Z.dump.gpg"; echo "$valid"; exit 0;;
    noname)  echo "[GNUPG:] GOODSIG ${SUBKEY: -16} sign"; echo "$valid"; exit 0;;
    revoked) echo "[GNUPG:] KEYREVOKED"; echo "[GNUPG:] REVKEYSIG ${SUBKEY: -16} sign"; note "$name"; echo "$valid"; exit 0;;
    expired) echo "[GNUPG:] EXPKEYSIG ${SUBKEY: -16} sign"; note "$name"; echo "$valid"; exit 0;;
    other) echo "[GNUPG:] GOODSIG ${OTHER: -16} other"; echo "[GNUPG:] VALIDSIG $OTHER 2026-11-14 1794614400 0 4 0 22 10 00 $OTHER"; exit 0;;
    bad)   echo "[GNUPG:] BADSIG ${SUBKEY: -16} sign"; exit 1;;
  esac
done
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
  if grep '^kubectl' "$S/log" | grep -v -- "--context test-context" | grep -q .; then echo "FAIL $name: a kubectl without --context"; failures=$((failures + 1)); fi
}
for b in db-block att-block; do
  run $b none restores
  run $b deploy_fails stops
  run $b pods_fail stops
  run $b replica stops
  run $b pod_left stops
done
# The signature, checked only when MAITY_BACKUP_SIGNER is set; a stop must come before any decryption.
export SUBKEY=B1B2B3B4B5B6B7B8B9B0B1B2B3B4B5B6B7B8B9B0 PRIMARY=A1A2A3A4A5A6A7A8A9A0A1A2A3A4A5A6A7A8A9A0 OTHER=C1C2C3C4C5C6C7C8C9C0C1C2C3C4C5C6C7C8C9C0
sig_run() { # block, name, MAITY_BACKUP_SIGNER, SIG (good, other, bad, missing), want: restores | stops
  local block=$1 name="$1/sig_$2" signer=$3 sig=$4 want=$5
  export S="$work/sig-$block-$2" FAIL=none SIG=$sig; mkdir -p "$S"; : > "$S/log"; cp "$work/plain.tar" "$S/plain"
  [ "$sig" = missing ] || : > "$S/backup.gpg.sig"
  ( cd "$S" && MAITY_BACKUP_SIGNER=$signer PATH="$work/bin:$PATH" sh -eu -c "$(cat "$work/$block")" restore test-context backup.gpg ) >"$S/out" 2>&1
  local got=$? reached=stops
  grep -q " exec " "$S/log" && reached=restores
  if [ "$want" = restores ] && [ "$reached" = restores ] && [ "$got" = 0 ]; then echo "ok   $name (restores)"
  elif [ "$want" = stops ] && [ "$reached" = stops ] && [ "$got" != 0 ] && ! grep -q '^gpg -d' "$S/log"; then echo "ok   $name (stops before decrypting, exit $got)"
  else echo "FAIL $name: $reached with exit $got (want $want)"; sed 's/^/     /' "$S/out"; failures=$((failures + 1)); fi
}
lower=$(printf '%s' "$SUBKEY" | tr A-F a-f)
for b in db-block att-block; do
  sig_run $b unset "" missing restores
  grep -q "signature is not checked" "$work/sig-$b-unset/out" && echo "ok   $b/sig_unset: says the signature is not checked" \
    || { echo "FAIL $b/sig_unset: no note"; failures=$((failures + 1)); }
  sig_run $b subkey "$SUBKEY" good restores
  sig_run $b primary "$PRIMARY" good restores
  sig_run $b spaced_lower "$(printf '%s' "$lower" | sed 's/..../& /g')" good restores
  sig_run $b other_key "$SUBKEY" other stops
  sig_run $b bad "$SUBKEY" bad stops
  sig_run $b renamed "$SUBKEY" renamed stops
  sig_run $b no_name "$SUBKEY" noname stops
  sig_run $b two_signatures "$SUBKEY" double stops
  sig_run $b revoked_key "$SUBKEY" revoked stops
  sig_run $b expired_key "$SUBKEY" expired stops
  sig_run $b missing "$SUBKEY" missing stops
  sig_run $b partial "${SUBKEY:0:16}" good stops
  sig_run $b not_hex "not a fingerprint" good stops
done
# Closing and opening the hub's NetworkPolicy. $S/np.json is the policy; RULES its rules at the start.
rules='[{"from": [{"namespaceSelector": {"matchLabels": {"kubernetes.io/metadata.name": "kube-system"}}}], "ports": [{"port": "http", "protocol": "TCP"}]}]'
# The hub's policy as the chart renders it; OTHERS (more policies in the namespace), SELECTOR and TYPES change it.
hub_selector='{"matchLabels": {"app.kubernetes.io/name": "maity-hub", "app.kubernetes.io/instance": "maity", "app.kubernetes.io/component": "hub"}}'
np_run() { # name, block, FAIL value, initial ingress (JSON or none), kept file (content, none), want: ok | stops
  local name=$1 block=$2 fail=$3 initial=$4 kept=$5 want=$6
  export S="$work/np-$name" FAIL=$fail; mkdir -p "$S"; : > "$S/log"
  local head="\"metadata\": {\"name\": \"maity-maity-hub\"}, \"spec\": {\"podSelector\": ${SELECTOR:-$hub_selector}, \"policyTypes\": ${TYPES:-[\"Ingress\"]}"
  if [ "$initial" = none ]; then printf '{%s}}\n' "$head" > "$S/np.json"
  else printf '{%s, "ingress": %s}}\n' "$head" "$initial" > "$S/np.json"; fi
  printf '%s\n' "${OTHERS:-[]}" > "$S/others.json"
  [ "$kept" = none ] || printf '%s\n' "$kept" > "$S/hub-ingress-rules.json"
  ( cd "$S" && PATH="$work/bin:$PATH" sh -eu -c "$(cat "$work/$block")" "${block%-block}" test-context ) >"$S/out" 2>&1
  local got=$? scaled=no
  grep -q " scale " "$S/log" && scaled=yes
  local result=stops; [ "$got" = 0 ] && result=ok
  if [ "$result" = "$want" ]; then echo "ok   np/$name ($result, exit $got, scaled $scaled)"
  else echo "FAIL np/$name: $result with exit $got (want $want)"; sed 's/^/     /' "$S/out"; failures=$((failures + 1)); fi
}
np_check() { # name, what, test command (in $S)
  local name=$1 what=$2; shift 2
  if ( cd "$work/np-$name" && eval "$*" ); then echo "ok   np/$name: $what"; else echo "FAIL np/$name: $what"; failures=$((failures + 1)); fi
}
canon() { python3 -c 'import json, sys; print(json.dumps(json.loads(sys.argv[1]), sort_keys=True))' "$1"; }
want_rules=$(canon "$rules")
# close: the rules kept, the policy empty, then the hub started
np_run close close-block none "$rules" none ok
np_check close "the rules are kept" '[ "$(cat hub-ingress-rules.json)" = "$want_rules" ]'
np_check close "the policy admits nobody" '! grep -q ingress np.json'
np_check close "the hub was started" 'grep -q " scale " log'
# a failed patch, a patch that did not take, a policy that cannot be read: the hub stays stopped
np_run close_patch_fails close-block patch_fails "$rules" none stops
np_check close_patch_fails "the hub was not started" '! grep -q " scale " log'
np_run close_patch_ignored close-block patch_ignored "$rules" none stops
np_check close_patch_ignored "the hub was not started" '! grep -q " scale " log'
np_run close_save_fails close-block np_get_fails "$rules" none stops
np_check close_save_fails "no file, the hub not started" '[ ! -e hub-ingress-rules.json ] && ! grep -q " scale " log'
# a second close (the file from the first one is there): refused, the kept rules untouched, nothing patched
# Policies add up: another one that admits traffic to the hub's pods, a hub policy that lost its Ingress type or its
# selector, and a policy list that cannot be read all keep the hub stopped.
other() { # name, podSelector, policyTypes, ingress
  printf '[{"metadata": {"name": "%s"}, "spec": {"podSelector": %s, "policyTypes": %s, "ingress": %s}}]' "$@"
}
OTHERS=$(other allow-hub '{}' '["Ingress"]' "$rules") np_run close_second_policy close-block none "$rules" none stops
np_check close_second_policy "the hub was not started" '! grep -q " scale " log'
OTHERS=$(other allow-hub '{"matchExpressions": [{"key": "app.kubernetes.io/component", "operator": "In", "values": ["hub"]}]}' '["Ingress"]' "$rules") \
  np_run close_second_policy_expr close-block none "$rules" none stops
# Fail closed: only a selector the template labels alone prove disjoint lets the block go on (a pod has labels its
# template lacks, such as pod-template-hash).
OTHERS=$(other hash '{"matchExpressions": [{"key": "pod-template-hash", "operator": "Exists"}]}' '["Ingress"]' '[{}]') \
  np_run close_other_template_hash close-block none "$rules" none stops
OTHERS=$(other unknown '{"matchExpressions": [{"key": "team", "operator": "Exists"}]}' '["Ingress"]' "$rules") \
  np_run close_other_unknown_key close-block none "$rules" none stops
OTHERS=$(other unknown-labels '{"matchLabels": {"team": "x"}}' '["Ingress"]' "$rules") \
  np_run close_other_unknown_label close-block none "$rules" none stops
# The shipped postgres policy (deploy/k3s-single/postgres-netpol.yaml), read from the file: it goes on.
OTHERS=$(python3 -c 'import json, sys, yaml; print(json.dumps([d for d in yaml.safe_load_all(open(sys.argv[1])) if d and d["spec"].get("ingress")]))' \
  "$root/deploy/k3s-single/postgres-netpol.yaml") np_run close_shipped_postgres_policy close-block none "$rules" none ok
OTHERS=$(other other-component '{"matchLabels": {"app.kubernetes.io/component": "migrate"}}' '["Ingress"]' "$rules") \
  np_run close_other_component close-block none "$rules" none ok
OTHERS=$(other not-hub '{"matchExpressions": [{"key": "app.kubernetes.io/component", "operator": "NotIn", "values": ["hub"]}]}' '["Ingress"]' "$rules") \
  np_run close_other_notin close-block none "$rules" none ok
SELECTOR='{"matchLabels": {"app.kubernetes.io/component": "hub"}, "matchExpressions": [{"key": "pod-template-hash", "operator": "DoesNotExist"}]}' \
  np_run close_selector_expressions close-block none "$rules" none stops
OTHERS=$(other hub-egress "$hub_selector" '["Egress"]' "$rules") np_run close_other_egress_only close-block none "$rules" none ok
OTHERS=$(other deny-hub "$hub_selector" '["Ingress"]' '[]') np_run close_other_deny close-block none "$rules" none ok
TYPES='["Egress"]' np_run close_egress_only close-block none "$rules" none stops
np_check close_egress_only "the hub was not started" '! grep -q " scale " log'
SELECTOR='{"matchLabels": {"app.kubernetes.io/component": "web"}}' np_run close_selector_changed close-block none "$rules" none stops
np_check close_selector_changed "the hub was not started" '! grep -q " scale " log'
np_run close_list_fails close-block np_list_fails "$rules" none stops
np_check close_list_fails "the hub was not started" '! grep -q " scale " log'
np_run close_rerun close-block none none "$rules" stops
np_check close_rerun "the kept rules untouched, nothing patched" '[ "$(cat hub-ingress-rules.json)" = "$rules" ] && ! grep -q " patch " log'
np_run close_already_closed close-block none none none stops
np_check close_already_closed "no file kept" '[ ! -e hub-ingress-rules.json ]'
# open: the rules back, the file removed only then
np_run open open-block none none "$rules" ok
np_check open "the policy has the rules again, the file is gone" '[ ! -e hub-ingress-rules.json ] && [ "$(python3 -c "import json; print(json.dumps(json.load(open(\"np.json\"))[\"spec\"][\"ingress\"], sort_keys=True))")" = "$want_rules" ]'
np_run open_patch_fails open-block patch_fails none "$rules" stops
np_check open_patch_fails "the file stays" '[ "$(cat hub-ingress-rules.json)" = "$rules" ]'
np_run open_patch_ignored open-block patch_ignored none "$rules" stops
np_check open_patch_ignored "the file stays" '[ -s hub-ingress-rules.json ]'
np_run open_empty_file open-block none none "[]" stops
np_check open_empty_file "nothing patched" '! grep -q " patch " log'
np_run open_no_file open-block none none none stops
np_run open_not_json open-block none none "not json" stops
np_check open_not_json "nothing patched" '! grep -q " patch " log'
for n in close open; do
  if grep -v -- "--context test-context" "$work/np-$n/log" | grep -q .; then echo "FAIL np/$n: a kubectl without --context"; failures=$((failures + 1)); fi
done
[ "$failures" = 0 ] && echo "all scenarios pass" || { echo "$failures scenario(s) failed"; exit 1; }
