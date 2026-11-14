#!/bin/bash
# Runs the two container scripts of deploy/k3s-single/backup.yaml (the attachment tar, then the dump) with a real gpg and a stub
# pg_dump that records its arguments and the password it got, the volumes as directories, and checks how the dump connects:
# with the Secret maity-hub-db-migrate the dump runs as the role in its URL, the password reaches pg_dump through PGPASSWORD and
# never through its arguments (which every user on the node can read), and the rest of the URL, a query included, is kept;
# without the Secret it runs as the superuser, as before; a URL that is not a postgresql:// URL, or whose user or password
# holds `%`, `/`, `?`, `#` or a second `@`, or whose query names a password or password file (in any case, or encoded),
# fails the Job before pg_dump starts; other query options such as sslmode are kept.
# Usage: deploy/scripts/test-backup-dump.sh   (no cluster needed; gpg 2.2+, GNU tar, python3 with PyYAML)
set -u
here=$(cd "$(dirname "$0")" && pwd)
root=$(cd "$here/../.." && pwd)
work=$(mktemp -d); trap 'gpgconf --homedir "$work/gh" --kill gpg-agent 2>/dev/null; rm -rf "$work"' EXIT
mkdir -p "$work/bin" "$work/gh"; chmod 700 "$work/gh"

python3 - "$root/deploy/k3s-single/backup.yaml" "$work" <<'PY'
import sys, yaml
docs = [d for d in yaml.safe_load_all(open(sys.argv[1])) if d and d["kind"] == "CronJob"]
pod = docs[0]["spec"]["jobTemplate"]["spec"]["template"]["spec"]
open(sys.argv[2] + "/init.sh", "w").write(pod["initContainers"][0]["args"][0])
open(sys.argv[2] + "/dump.sh", "w").write(pod["containers"][0]["args"][0])
PY
for f in init.sh dump.sh; do [ -s "$work/$f" ] || { echo "FAIL could not read $f from backup.yaml"; exit 1; }; done

# The stub writes its arguments and its PGPASSWORD to the run's directory.
cat > "$work/bin/pg_dump" <<'STUB'
#!/bin/sh
printf '%s\n' "$*" > "$RUN/argv"
printf '%s\n' "${PGPASSWORD:-}" > "$RUN/password"
printf 'PGDMP a dump\n'
STUB
chmod +x "$work/bin/pg_dump"

gpg --batch --quiet --homedir "$work/gh" --passphrase "" --quick-gen-key "enc <e@example.org>" default default never
gpg --batch --quiet --homedir "$work/gh" --armor --export "enc <e@example.org>" > "$work/backup.pub"

failures=0
fail() { echo "FAIL $1"; [ -n "${2:-}" ] && sed 's/^/     /' "$2"; failures=$((failures + 1)); }

run() { # name, DUMP_URL or none; sets W and rc (0, init or dump)
  W="$work/run-$1"; mkdir -p "$W/backups" "$W/attachments" "$W/ts" "$W/key"
  echo file > "$W/attachments/f"
  cp "$work/backup.pub" "$W/key/backup.pub"
  for f in init dump; do
    sed -E "s#([ =])/(backups|attachments|ts|key)([/ ]|\$)#\\1$W/\\2\\3#g" "$work/$f.sh" > "$W/$f.sh"
  done
  rc=0
  ( PATH="$work/bin:$PATH" sh -ec "$(cat "$W/init.sh")" ) > "$W/init.out" 2>&1 || rc=init
  if [ "$rc" = 0 ]; then
    if [ "$2" = none ]; then
      ( RUN=$W PGPASSWORD=superpw PATH="$work/bin:$PATH" sh -ec "$(cat "$W/dump.sh")" ) > "$W/dump.out" 2>&1 || rc=dump
    else
      ( RUN=$W PGPASSWORD=superpw DUMP_URL=$2 PATH="$work/bin:$PATH" sh -ec "$(cat "$W/dump.sh")" ) > "$W/dump.out" 2>&1 || rc=dump
    fi
  fi
  cat "$W/init.out" "$W/dump.out" > "$W/out" 2>/dev/null
}
dumped() { # name, the arguments wanted, the password wanted
  if [ "$rc" != 0 ]; then fail "$1: the Job failed ($rc)" "$W/out"; return; fi
  grep -q '^dump ok: ' "$W/out" || fail "$1: no dump ok line" "$W/out"
  [ "$(cat "$W/argv")" = "$2" ] && echo "ok   $1: pg_dump $2" || fail "$1: pg_dump got '$(cat "$W/argv")', want '$2'"
  [ "$(cat "$W/password")" = "$3" ] && echo "ok   $1: the password came through PGPASSWORD" || fail "$1: PGPASSWORD was '$(cat "$W/password")', want '$3'"
}
refused() { # name, text in the output
  if [ "$rc" != dump ]; then fail "$1: the Job did not fail in the dump ($rc)" "$W/out"; return; fi
  [ -e "$W/argv" ] && fail "$1: pg_dump ran" || echo "ok   $1: pg_dump did not run"
  grep -qF "$2" "$W/out" && echo "ok   $1: says \"$2\"" || fail "$1: does not say \"$2\"" "$W/out"
}

run owner "postgresql://maity_owner:Ownerpw123@maity-postgres:5432/maity"
dumped owner "-Fc -d postgresql://maity_owner@maity-postgres:5432/maity" Ownerpw123
grep -q Ownerpw123 "$W/argv" && fail "owner: the password is in pg_dump's arguments" || echo "ok   owner: no password in pg_dump's arguments"

run query "postgres://maity_owner:Ownerpw123@db.example.org/maity?sslmode=verify-full&connect_timeout=10"
dumped query "-Fc -d postgresql://maity_owner@db.example.org/maity?sslmode=verify-full&connect_timeout=10" Ownerpw123

run no-password "postgresql://maity_owner@maity-postgres:5432/maity"
dumped no-password "-Fc -d postgresql://maity_owner@maity-postgres:5432/maity" superpw

run superuser none
dumped superuser "-Fc -h maity-postgres -U maity maity" superpw

bad="holds %, /, ?, # or @"
run encoded "postgresql://maity_owner:a%40b@maity-postgres:5432/maity"
refused encoded "$bad"
# Unencoded `/` or `@` in the password: the split cannot be certain, so nothing reaches pg_dump.
run slash "postgresql://maity_owner:ab/cd@maity-postgres/maity"
refused slash "$bad"
run two-ats "postgresql://maity_owner:a@b@maity-postgres/maity"
refused two-ats "$bad"
run question "postgresql://maity_owner:ab?cd@maity-postgres/maity"
refused question "$bad"

run not-url "host=maity-postgres user=maity_owner password=Ownerpw123 dbname=maity"
refused not-url "is not a postgresql:// URL"

# A password or password file in the query would reach the arguments as well: refused, whatever the case or encoding.
q="the query of maity-hub-db-migrate's database-url holds a password"
run query-password "postgresql://maity_owner@maity-postgres/maity?password=Querypw123"
refused query-password "$q"
run query-upper "postgresql://maity_owner:Ownerpw123@maity-postgres/maity?sslmode=require&PASSWORD=Querypw123"
refused query-upper "$q"
run query-encoded "postgresql://maity_owner@maity-postgres/maity?pass%77ord=Querypw123"
refused query-encoded "$q"
run query-passfile "postgresql://maity_owner@maity-postgres/maity?passfile=/tmp/pgpass"
refused query-passfile "$q"
run query-sslmode "postgresql://maity_owner:Ownerpw123@maity-postgres/maity?sslmode=require&sslrootcert=/certs/ca.pem"
dumped query-sslmode "-Fc -d postgresql://maity_owner@maity-postgres/maity?sslmode=require&sslrootcert=/certs/ca.pem" Ownerpw123

[ "$failures" = 0 ] && echo "all scenarios pass" || { echo "$failures scenario(s) failed"; exit 1; }
