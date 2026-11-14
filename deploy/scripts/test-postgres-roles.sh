#!/bin/bash
# Runs deploy/postgres-roles.sql against a real PostgreSQL with restores in between (docs/install/README.md, "Database roles"):
# a dump from before the two roles, restored into a database that has them, brings its objects back owned by the superuser
# and without the app role's rights; the script run again afterwards, without passwords, hands them back and grants the rows,
# and keeps the passwords. Also: a dump made after the split restores with the rights; `after_restore` does nothing where the
# roles were never set up; without passwords the script refuses to create a role; passwords given again replace them.
# The roles get names of their own (t_roles_owner, t_roles_app), made and dropped here.
# Usage, from the checkout's root:
#   hub/scripts/with_postgres.sh deploy/scripts/test-postgres-roles.sh     (psql, pg_dump, pg_restore; PYTHON with the hub's
#                                                                             dependencies, default python3)
set -u
root=$(cd "$(dirname "$0")/../.." && pwd)
python=${PYTHON:-python3}
url=${MAITY_TEST_DATABASE_URL:?run under hub/scripts/with_postgres.sh}
work=$(mktemp -d); trap 'rm -rf "$work"' EXIT
owner=t_roles_owner app=t_roles_app
sed -e "s/maity_owner/$owner/g" -e "s/maity_app/$app/g" "$root/deploy/postgres-roles.sql" > "$work/roles.sql"

# url_for user database: the test URL with another user (no password: the test server's socket) and database
url_for() { "$python" -c 'import sys, urllib.parse as u; p = u.urlsplit(sys.argv[1]); h = p.netloc.split("@")[-1]
print(u.urlunsplit((p.scheme, sys.argv[2] + "@" + h, "/" + sys.argv[3], p.query, "")))' "$url" "$1" "$2"; }
base=$("$python" -c 'import sys, urllib.parse as u; print(u.urlsplit(sys.argv[1]).path.lstrip("/"))' "$url")
superuser=$("$python" -c 'import sys, urllib.parse as u; print(u.urlsplit(sys.argv[1]).username)' "$url")
failures=0
ok() { echo "ok   $*"; }
fail() { echo "FAIL $*"; failures=$((failures + 1)); }
with_passwords() { { printf "%s '%s'\n" '\set owner_password' "$2" '\set app_password' "$3"; cat "$work/roles.sql"; } | psql -X -q -v ON_ERROR_STOP=1 "$1"; }
after_restore() { psql -X -q -v ON_ERROR_STOP=1 -v after_restore=1 "$1" < "$work/roles.sql"; }
database() { psql -X -q "$url" -c "drop database if exists \"${base}_$1\"" -c "create database \"${base}_$1\"" >/dev/null; url_for "$superuser" "${base}_$1"; }
migrate() { MAITY_DATABASE_URL=$1 PYTHONPATH="$root/hub/src" "$python" -m maity_hub migrate > "$work/migrate.log" 2>&1; }
lacking() { # tables of the database at $1 that the app role cannot read and write
  psql -X -At "$1" -c "with t as materialized (select c.oid from pg_class c join pg_namespace n on n.oid = c.relnamespace
    where n.nspname = 'public' and c.relkind = 'r') select count(*) from t where not has_table_privilege('$app', t.oid, 'SELECT,INSERT,UPDATE,DELETE')"
}
not_owned() { psql -X -At "$1" -c "select count(*) from pg_class c join pg_namespace n on n.oid = c.relnamespace
  where n.nspname = 'public' and c.relkind in ('r', 'S') and c.relowner <> '$owner'::regrole"; }
hashes() { psql -X -At "$url" -c "select string_agg(rolname || '=' || coalesce(rolpassword, ''), ' ' order by rolname) from pg_authid where rolname in ('$owner', '$app')"; }
drop_roles() { psql -X -q "$url" -c "drop role if exists $owner" -c "drop role if exists $app" 2>/dev/null; }
cleanup() { for d in old new later; do psql -X -q "$url" -c "drop database if exists \"${base}_$d\"" >/dev/null 2>&1; done; drop_roles; }
trap 'cleanup; rm -rf "$work"' EXIT
cleanup

# Without passwords and without roles: an error, nothing made; with after_restore: nothing to do.
old=$(database old)
if psql -X -q -v ON_ERROR_STOP=1 "$old" < "$work/roles.sql" > "$work/out" 2>&1; then fail "no passwords, no roles: the script went on"
elif grep -q "a role to create needs one" "$work/out"; then ok "no passwords, no roles: the script stops and names the passwords"
else fail "no passwords, no roles: another error"; sed 's/^/     /' "$work/out"; fi
after_restore "$old" > "$work/out" 2>&1 && grep -q "nothing to hand over" "$work/out" \
  && ok "after_restore without roles: nothing to do" || { fail "after_restore without roles"; sed 's/^/     /' "$work/out"; }
[ -z "$(hashes)" ] && ok "no role was made" || fail "roles made: $(hashes)"

# A dump from before the two roles: migrated and owned by the superuser.
migrate "$old" || { fail "migrate as the superuser"; tail -5 "$work/migrate.log"; }
pg_dump -Fc -d "$old" -f "$work/old.dump"

# Into a new PostgreSQL: the roles first, the restore as the superuser, then the script again.
new=$(database new)
with_passwords "$new" owner-secret-1 app-secret-1
kept=$(hashes)
pg_restore -d "$new" "$work/old.dump" 2> "$work/restore.log"
n=$(lacking "$new"); [ "$n" -gt 0 ] && ok "the restore alone: $n tables without the app role's rights (the dump names the superuser)" \
  || fail "the restore alone left the app role every table (the case this test is for did not happen)"
after_restore "$new" || fail "the script after the restore"
n=$(lacking "$new"); [ "$n" = 0 ] && ok "the script after the restore: the app role reads and writes every table" || fail "after the script: $n tables without rights"
n=$(not_owned "$new"); [ "$n" = 0 ] && ok "the script after the restore: everything belongs to the owner role" || fail "after the script: $n objects not the owner's"
[ "$(hashes)" = "$kept" ] && ok "the run without passwords kept both passwords" || fail "the run without passwords changed a password"
migrate "$(url_for "$owner" "${base}_new")" && ok "migrate as the owner role after the restore" || { fail "migrate as the owner role"; tail -5 "$work/migrate.log"; }

# The k3s block's way: pg_restore --clean into the running database, then the script.
pg_restore -d "$new" --clean --if-exists "$work/old.dump" 2> "$work/restore.log"
n=$(lacking "$new"); [ "$n" -gt 0 ] && ok "--clean restore of the old dump: $n tables lose the app role's rights" || fail "--clean restore: no rights lost"
after_restore "$new"
n=$(lacking "$new"); [ "$n" = 0 ] && ok "--clean restore, then the script: every table again" || fail "--clean, then the script: $n tables without rights"

# A dump made after the split names the owner role: it restores with the rights; the script after it is harmless.
pg_dump -Fc -d "$new" -f "$work/new.dump"
later=$(database later)
with_passwords "$later" owner-secret-1 app-secret-1
pg_restore -d "$later" "$work/new.dump" 2> "$work/restore.log"
n=$(lacking "$later"); [ "$n" = 0 ] && ok "a dump from after the split restores with the app role's rights" || fail "the later dump: $n tables without rights"
after_restore "$later"
n=$(lacking "$later"); [ "$n" = 0 ] && ok "the script after it changes nothing" || fail "the script after the later dump: $n tables without rights"

# Passwords given again replace both.
with_passwords "$later" owner-secret-2 app-secret-2
[ "$(hashes)" != "$kept" ] && ok "passwords given again replace them" || fail "passwords not replaced"

[ "$failures" = 0 ] && echo "all scenarios pass" || { echo "$failures failure(s)"; exit 1; }
