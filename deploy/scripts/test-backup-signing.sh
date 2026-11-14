#!/bin/bash
# Runs the two container scripts of deploy/k3s-single/backup.yaml (the attachment tar, then the dump) with a real gpg and a stub
# pg_dump, the volumes as directories, and checks the signatures: without the Secret maity-backup-signing-key the backups are
# written unsigned with a warning; with a signing key each encrypted file gets a detached <file>.sig that verifies with that key's
# fingerprint and carries the file's name as a signed notation; a key that cannot sign (a passphrase, a public key only), that can
# also decrypt, or that is the encryption key fails the Job before anything is written; a signature whose file is gone is removed
# with the rotation. Then it runs the two documented restore blocks (docs/install/README.md, restore-attachments.yaml) with that
# gpg against the files the Job wrote, kubectl and pg_restore stubbed: a backup under its own name restores, an older backup with
# its signature renamed to a newer time stamp stops before it is decrypted, and so does one whose .sig adds a second signature,
# by another key, carrying the newer name.
# Usage: deploy/scripts/test-backup-signing.sh   (no cluster needed; gpg 2.2+, GNU tar, python3 with PyYAML)
set -u
here=$(cd "$(dirname "$0")" && pwd)
root=$(cd "$here/../.." && pwd)
work=$(mktemp -d); trap 'for h in "$work"/gh-*; do gpgconf --homedir "$h" --kill gpg-agent 2>/dev/null; done; rm -rf "$work"' EXIT
mkdir -p "$work/bin"

python3 - "$root/deploy/k3s-single/backup.yaml" "$work" <<'PY'
import sys, yaml
docs = [d for d in yaml.safe_load_all(open(sys.argv[1])) if d and d["kind"] == "CronJob"]
pod = docs[0]["spec"]["jobTemplate"]["spec"]["template"]["spec"]
open(sys.argv[2] + "/init.sh", "w").write(pod["initContainers"][0]["args"][0])
open(sys.argv[2] + "/dump.sh", "w").write(pod["containers"][0]["args"][0])
PY
for f in init.sh dump.sh; do [ -s "$work/$f" ] || { echo "FAIL could not read $f from backup.yaml"; exit 1; }; done

cat > "$work/bin/pg_dump" <<'STUB'
#!/bin/sh
printf 'PGDMP a dump\n'
STUB
chmod +x "$work/bin/pg_dump"

# Keys: an encryption key pair, a signing key without a passphrase, one with a passphrase.
gh() { local h="$work/gh-$1"; mkdir -p "$h"; chmod 700 "$h"; echo "$h"; }
K=$(gh keys)
gk() { gpg --batch --quiet --homedir "$K" "$@"; }
gk --passphrase "" --quick-gen-key "enc <e@example.org>" default default never
gk --armor --export "enc <e@example.org>" > "$work/backup.pub"
gk --passphrase "" --quick-gen-key "sign <s@example.org>" ed25519 sign never
signer=$(gk --with-colons --list-keys "sign <s@example.org>" | awk -F: '$1 == "fpr" {print $10; exit}')
gk --armor --export-secret-keys "sign <s@example.org>" > "$work/signing.key"
gk --armor --export "sign <s@example.org>" > "$work/signing.pub"
gk --pinentry-mode loopback --passphrase secret --quick-gen-key "locked <l@example.org>" ed25519 sign never
gk --pinentry-mode loopback --passphrase secret --armor --export-secret-keys "locked <l@example.org>" > "$work/locked.key"

failures=0
fail() { echo "FAIL $1"; [ -n "${2:-}" ] && sed 's/^/     /' "$2"; failures=$((failures + 1)); }

run() { # name, signing key file or none, [public key for maity-backup-key]; sets W and the Job's failed container (or 0) in rc
  W="$work/run-$1"; mkdir -p "$W/backups" "$W/attachments" "$W/ts" "$W/key" "$W/signing"
  echo file > "$W/attachments/f"
  cp "${3:-$work/backup.pub}" "$W/key/backup.pub"
  [ "$2" = none ] || cp "$2" "$W/signing/backup-signing.key"
  for f in init dump; do
    sed -E "s#([ =])/(backups|attachments|ts|key|signing)([/ ]|\$)#\\1$W/\\2\\3#g" "$work/$f.sh" > "$W/$f.sh"
  done
  # an old signature whose backup is gone, which the rotation removes
  : > "$W/backups/maity-20000101T000000Z.dump.gpg.sig"
  rc=0
  ( PATH="$work/bin:$PATH" sh -ec "$(cat "$W/init.sh")" ) > "$W/init.out" 2>&1 || rc=init
  [ "$rc" != 0 ] || ( PATH="$work/bin:$PATH" sh -ec "$(cat "$W/dump.sh")" ) > "$W/dump.out" 2>&1 || rc=dump
  cat "$W/init.out" "$W/dump.out" > "$W/out" 2>/dev/null
}
written() { ls "$W/backups" | grep -E '^maity-[0-9]{8}T[0-9]{6}Z\.(dump|attachments\.tar)\.gpg$' ; }
verify() { # file: verifies against the signing key's public half in a fresh home, prints the signer's fingerprint and the signed name
  local h; h=$(gh "v-$(basename "$W")"); gpg --batch --quiet --homedir "$h" --import "$work/signing.pub" 2>/dev/null
  gpg --batch --homedir "$h" --status-fd 1 --verify "$1.sig" "$1" 2>/dev/null \
    | awk '$2 == "VALIDSIG" {v = $3} $2 == "NOTATION_NAME" {n = $3} $2 == "NOTATION_DATA" && n == "backup-file@maity" {d = $3} END {print v, d}'
}

# 1. No signing key: both files written, no signature, a warning, "unsigned" in the dump ok line.
run unsigned none
if [ "$rc" != 0 ]; then fail "unsigned: the Job failed ($rc)" "$W/out"
else
  [ "$(written | wc -l)" = 2 ] && echo "ok   unsigned: dump and tar written" || fail "unsigned: not both files written" "$W/out"
  ls "$W/backups" | grep -q '^maity-2[1-9].*\.sig$' && fail "unsigned: a signature was written" || echo "ok   unsigned: no signature"
  grep -q "warning: the backups are not signed" "$W/out" && echo "ok   unsigned: the log warns" || fail "unsigned: no warning" "$W/out"
  grep -q "^dump ok: .*(encrypted, unsigned;" "$W/out" && echo "ok   unsigned: the dump ok line says unsigned" || fail "unsigned: dump ok line" "$W/out"
fi

# 2. A signing key: each file has a signature by that key, made over the encrypted file.
run signed "$work/signing.key"
if [ "$rc" != 0 ]; then fail "signed: the Job failed ($rc)" "$W/out"
else
  for f in $(written); do
    got=$(verify "$W/backups/$f")
    [ "$got" = "$signer $f" ] && echo "ok   signed: $f verifies with the signing key, under its own name" || fail "signed: $f does not verify (got '$got')" "$W/out"
  done
  [ "$(written | wc -l)" = 2 ] || fail "signed: not both files written" "$W/out"
  grep -q "^dump ok: .*(encrypted, signed by $signer;" "$W/out" && echo "ok   signed: the dump ok line names the fingerprint" || fail "signed: dump ok line" "$W/out"
  grep -q "warning" "$W/out" && fail "signed: a warning although signed" "$W/out" || echo "ok   signed: no warning"
  [ -e "$W/backups/maity-20000101T000000Z.dump.gpg.sig" ] && fail "signed: the orphaned signature is still there" || echo "ok   signed: an orphaned signature is removed"
  ls "$W/backups" | grep -q '\.part$' && fail "signed: a .part is left" || echo "ok   signed: no .part left"
  # a changed byte in the encrypted file no longer verifies
  f=$(written | head -1); printf 'x' >> "$W/backups/$f"
  [ "$(verify "$W/backups/$f")" = " " ] && echo "ok   signed: a changed file does not verify" || fail "signed: a changed file verifies"
fi

# 3. Keys that cannot sign, or must not: the Job fails before it writes anything.
gk --armor --export-secret-keys "enc <e@example.org>" > "$work/enc.key"
gk --passphrase "" --quick-gen-key "other <o@example.org>" default default never   # signs and decrypts, not the recipient
gk --armor --export-secret-keys "other <o@example.org>" > "$work/other.key"
refused() { # name, signing key, expected message, [public key for maity-backup-key]
  run "$1" "$2" "${4:-}"
  if [ "$rc" = init ] && [ -z "$(written)" ] && grep -q "backup failed: maity-backup-signing-key $3" "$W/out"; then
    echo "ok   $1: the Job fails before writing ($3)"
  else fail "$1: rc=$rc, written: $(written | tr '\n' ' ')" "$W/out"; fi
}
refused passphrase "$work/locked.key" "cannot sign"
refused public-only "$work/signing.pub" "cannot sign"
refused decrypting "$work/other.key" "can also decrypt"
refused encryption-key "$work/enc.key" "can also decrypt"
# the signing key itself as maity-backup-key: same fingerprint, though it cannot decrypt
refused same-key "$work/signing.key" "is the key in maity-backup-key" "$work/signing.pub"
# two signing keys in one Secret (an old one left in): which one signs would be gpg's choice
gk --passphrase "" --quick-gen-key "sign2 <s2@example.org>" ed25519 sign never
gk --armor --export-secret-keys "sign2 <s2@example.org>" > "$work/sign2.key"
cat "$work/signing.key" "$work/sign2.key" > "$work/two.key"
refused two-keys "$work/two.key" "holds more than one key"

# 4. The documented restore blocks with the real gpg, against the files of a fresh Job run. The fingerprint is set; GNUPGHOME
# has the decryption key and the signing key's public half.
extract() { # file, the line that ends the block, prefix to strip (as in test-restore-blocks.sh)
  awk -v end="$2" -v pre="$3" '
    { line = $0; if (pre != "" && index(line, pre) == 1) line = substr(line, length(pre) + 1); sub(/^[ \t]+/, "", line) }
    inside && index(line, end) == 1 { exit }
    inside { print line }
    index(line, "sh -eu -c '"'"'") == 1 { inside = 1 }
  ' "$1"
}
extract "$root/docs/install/README.md" "' restore <kube context> maity-<UTC time>.dump.gpg" "" > "$work/db-block"
extract "$root/deploy/k3s-single/restore-attachments.yaml" "' restore <kube context>" "#   " > "$work/att-block"
# A block that reads deploy/postgres-roles.sql from the checkout's root gets its absolute path (no change while it reads none).
sed -i "s#< deploy/postgres-roles.sql#< $root/deploy/postgres-roles.sql#" "$work/db-block"
for b in db-block att-block; do grep -q "NOTATION_DATA" "$work/$b" || { echo "FAIL the $b has no name check"; exit 1; }; done
cat > "$work/bin/kubectl" <<'STUB'
#!/bin/bash
echo "kubectl $*" >> "$R/log"
case "$*" in
  *"get deploy"*) printf 0;;
  *" exec "*)     cat > /dev/null;;
  *"create secret generic maity-backup-signing-key"*)   # the key file the Secret would get
                  for a in "$@"; do case "$a" in --from-file=*) cp "${a##*=}" "$R/exported.key";; esac; done;;
esac
exit 0
STUB
printf '#!/bin/sh\nexit 0\n' > "$work/bin/pg_restore"
chmod +x "$work/bin/kubectl" "$work/bin/pg_restore"
run restore "$work/signing.key"
[ "$rc" = 0 ] || fail "restore: the Job failed ($rc)" "$W/out"
new=$(written | grep 'dump\.gpg$' | sed 's/maity-\(.*\)Z\.dump\.gpg/\1/')
# a genuine backup and its genuine signature, renamed to a later night's time stamp
for kind in dump attachments.tar; do
  for x in "" .sig; do cp "$W/backups/maity-${new}Z.$kind.gpg$x" "$W/backups/maity-29991231T000000Z.$kind.gpg$x"; done
done
# the same, but its .sig also holds a second signature, by another key in the keyring, carrying the later name
for kind in dump attachments.tar; do
  later="maity-29991230T000000Z.$kind.gpg"
  cp "$W/backups/maity-${new}Z.$kind.gpg" "$W/backups/$later"
  gk --local-user "sign2 <s2@example.org>" --sig-notation "backup-file@maity=$later" --detach-sign \
    --output "$work/second-$kind.sig" "$W/backups/$later"
  cat "$W/backups/maity-${new}Z.$kind.gpg.sig" "$work/second-$kind.sig" > "$W/backups/$later.sig"
done
restore() { # name, block, file in $W/backups, want: restores | stops
  export R="$work/r-$1"; mkdir -p "$R"; : > "$R/log"
  ( cd "$W/backups" && GNUPGHOME="$K" MAITY_BACKUP_SIGNER=$signer PATH="$work/bin:$PATH" sh -eu -c "$(cat "$work/$2")" restore test-context "$3" ) > "$R/out" 2>&1
  local got=$? reached=stops
  grep -q " exec " "$R/log" && reached=restores
  local status_ok=no
  if [ "$4" = restores ]; then [ "$got" = 0 ] && status_ok=yes; else [ "$got" != 0 ] && status_ok=yes; fi
  if [ "$reached" = "$4" ] && [ "$status_ok" = yes ]; then echo "ok   restore/$1 ($reached, exit $got)"
  else fail "restore/$1: $reached with exit $got (want $4)" "$R/out"; fi
}
for kind in dump attachments.tar; do
  b=db-block; [ "$kind" = dump ] || b=att-block
  restore "$kind-own-name" $b "maity-${new}Z.$kind.gpg" restores
  restore "$kind-renamed" $b "maity-29991231T000000Z.$kind.gpg" stops
  restore "$kind-second-signature" $b "maity-29991230T000000Z.$kind.gpg" stops
  grep -q "more than one signature" "$work/r-$kind-second-signature/out" && echo "ok   restore/$kind-second-signature: names the reason" \
    || fail "restore/$kind-second-signature: no reason" "$work/r-$kind-second-signature/out"
  grep -q "signed under another name" "$work/r-$kind-renamed/out" && echo "ok   restore/$kind-renamed: names the reason" || fail "restore/$kind-renamed: no reason" "$work/r-$kind-renamed/out"
done

# 5. A revoked signing key: the same backups no longer restore. The revocation certificate gpg made with the key.
sed 's/^:-----BEGIN/-----BEGIN/' "$K/openpgp-revocs.d/$signer.rev" | gk --import 2>/dev/null
for kind in dump attachments.tar; do
  b=db-block; [ "$kind" = dump ] || b=att-block
  restore "$kind-revoked-key" $b "maity-${new}Z.$kind.gpg" stops
  grep -q "revoked or expired" "$work/r-$kind-revoked-key/out" && echo "ok   restore/$kind-revoked-key: names the reason" \
    || fail "restore/$kind-revoked-key: no reason" "$work/r-$kind-revoked-key/out"
done

# 6. The key setup of docs/install/README.md, step 4, run twice as a rotation is: each run hands the Secret only the key it
# made, picked by its fingerprint, though both keys have the same user ID.
setup="$work/setup.sh"
awk '/^fpr=\$\(gpg --batch --yes --status-fd 1/ {on = 1} on {print} on && /^echo "\$fpr"/ {exit}' "$root/docs/install/README.md" > "$setup"
grep -q 'export-secret-keys "$fpr!"' "$setup" || { echo "FAIL could not read the key setup from the install guide"; exit 1; }
H=$(gh setup)
for n in 1 2; do
  export R="$work/setup-$n"; mkdir -p "$R"; : > "$R/log"
  printed=$(cd "$R" && GNUPGHOME="$H" PATH="$work/bin:$PATH" sh -e "$setup" 2>"$R/err")
  keys=$(gpg --batch --homedir "$(gh "count-$n")" --with-colons --show-keys "$R/exported.key" 2>/dev/null)
  secs=$(printf '%s\n' "$keys" | grep -c '^sec:')
  got=$(printf '%s\n' "$keys" | awk -F: '$1 == "fpr" {print $10; exit}')
  if [ "$secs" = 1 ] && [ "$got" = "$printed" ] && printf '%s' "$printed" | grep -qxE '[0-9A-F]{40}' && [ ! -e "$R/backup-signing.key" ]; then
    echo "ok   setup run $n: the Secret gets only the new key ($printed)"
  else fail "setup run $n: $secs keys, exported $got, printed '$printed'" "$R/err"; fi
  eval "fpr_$n=$printed"
done
[ -n "$fpr_1" ] && [ -n "$fpr_2" ] && [ "$fpr_1" != "$fpr_2" ] && echo "ok   setup: the second run made a new key" || fail "setup: the same key twice"

[ "$failures" = 0 ] && echo "all scenarios pass" || { echo "$failures failure(s)"; exit 1; }
