#!/bin/bash
# Runs the two container scripts of deploy/k3s-single/backup.yaml (the attachment tar, then the dump) with a real gpg and a stub
# pg_dump, the volumes as directories, and checks the signatures: without the Secret maity-backup-signing-key the backups are
# written unsigned with a warning; with a signing key each encrypted file gets a detached <file>.sig that verifies with that key's
# fingerprint; a key that cannot sign (a passphrase, a public key only) fails the Job before anything is written; a signature
# whose file is gone is removed with the rotation.
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

run() { # name, signing key file or none; sets W and the exit status of the Job (init, then dump) in rc
  W="$work/run-$1"; mkdir -p "$W/backups" "$W/attachments" "$W/ts" "$W/key" "$W/signing"
  echo file > "$W/attachments/f"
  cp "$work/backup.pub" "$W/key/backup.pub"
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
verify() { # file: verifies against the signing key's public half in a fresh home, prints the signer's fingerprint
  local h; h=$(gh "v-$(basename "$W")"); gpg --batch --quiet --homedir "$h" --import "$work/signing.pub" 2>/dev/null
  gpg --batch --homedir "$h" --status-fd 1 --verify "$1.sig" "$1" 2>/dev/null | awk '$2 == "VALIDSIG" {print $3}'
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
    [ "$got" = "$signer" ] && echo "ok   signed: $f verifies with the signing key" || fail "signed: $f does not verify (got '$got')" "$W/out"
  done
  [ "$(written | wc -l)" = 2 ] || fail "signed: not both files written" "$W/out"
  grep -q "^dump ok: .*(encrypted, signed by $signer;" "$W/out" && echo "ok   signed: the dump ok line names the fingerprint" || fail "signed: dump ok line" "$W/out"
  grep -q "warning" "$W/out" && fail "signed: a warning although signed" "$W/out" || echo "ok   signed: no warning"
  [ -e "$W/backups/maity-20000101T000000Z.dump.gpg.sig" ] && fail "signed: the orphaned signature is still there" || echo "ok   signed: an orphaned signature is removed"
  ls "$W/backups" | grep -q '\.part$' && fail "signed: a .part is left" || echo "ok   signed: no .part left"
  # a changed byte in the encrypted file no longer verifies
  f=$(written | head -1); printf 'x' >> "$W/backups/$f"
  [ -z "$(verify "$W/backups/$f")" ] && echo "ok   signed: a changed file does not verify" || fail "signed: a changed file verifies"
fi

# 3. Keys that cannot sign: the Job fails before it writes anything.
for k in locked signing.pub; do
  key="$work/$k"; [ "$k" = locked ] && key="$work/locked.key"
  run "cannot-$k" "$key"
  if [ "$rc" = init ] && [ -z "$(written)" ] && grep -q "backup failed: maity-backup-signing-key" "$W/out"; then
    echo "ok   $k: the Job fails before writing"
  else fail "$k: rc=$rc, written: $(written | tr '\n' ' ')" "$W/out"; fi
done

[ "$failures" = 0 ] && echo "all scenarios pass" || { echo "$failures failure(s)"; exit 1; }
