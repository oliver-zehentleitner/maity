#!/usr/bin/env bash
# Runs a command against a local PostgreSQL, in a database of its own:
#
#   scripts/with_postgres.sh pytest -n 2 tests/test_board.py
#
# Several runs can share one server. The last run to end stops it, and only if a run of this
# script started it: a server that was already up keeps running. MAITY_TEST_DATABASE_URL is
# set for the command. MAITY_PG_DIR is the data directory (created when missing), MAITY_PG_BIN
# the directory of pg_ctl when it is not on the path.
set -euo pipefail

if [ "$#" -eq 0 ]; then
  echo "usage: $0 <command> [argument ...]" >&2
  exit 2
fi

dir="${MAITY_PG_DIR:-${XDG_STATE_HOME:-$HOME/.local/state}/maity/test-postgres}"
if [ -n "${MAITY_PG_BIN:-}" ]; then
  PATH="$MAITY_PG_BIN:$PATH"
fi
for tool in pg_ctl initdb psql flock; do
  if ! command -v "$tool" >/dev/null; then
    echo "$0: $tool not found; set MAITY_PG_BIN to PostgreSQL's bin directory (hub/README.md)" >&2
    exit 2
  fi
done

locks="$dir.locks"
mkdir -p "$locks"
started="$locks/started-by-script" # the process id of a server this script started
exec 8>"$locks/state" 9>"$locks/users"

# The state lock covers looking at the server and starting or stopping it. Fd 9 is held shared
# for as long as a run uses the server. Neither reaches the server or the command: a process
# that inherits a lock holds it.
flock -x 8
if [ ! -f "$dir/PG_VERSION" ]; then
  initdb -D "$dir" -U postgres -A trust >/dev/null 8>&- 9>&-
fi
if ! pg_ctl -D "$dir" status >/dev/null 2>&1; then
  pg_ctl -D "$dir" -w -l "$dir/server.log" -o "-c listen_addresses='' -k '$dir'" start >/dev/null 8>&- 9>&-
  head -n 1 "$dir/postmaster.pid" >"$started"
fi
flock -s 9
flock -u 8

database="maity_test_$$"
sql() { psql -h "$dir" -U postgres -d postgres -qAt -v ON_ERROR_STOP=1 -c "$1" 8>&- 9>&-; }

finish() {
  # The database and the ones pytest -n made beside it (conftest: <name>_gw0, ...).
  for name in $(sql "select datname from pg_database where datname = '$database' or datname like '${database}\_gw%'"); do
    sql "drop database if exists \"$name\" with (force)" || true
  done
  flock -x 8
  if flock -x -n 9 && [ -f "$started" ]; then # no other run holds the server
    # The same process as the one started: a mark left by a killed run names no later server.
    if [ "$(head -n 1 "$dir/postmaster.pid" 2>/dev/null)" = "$(cat "$started")" ]; then
      pg_ctl -D "$dir" -m fast stop >/dev/null 8>&- 9>&- || true
    fi
    rm -f "$started"
  fi
}
trap finish EXIT

sql "create database $database"
export MAITY_TEST_DATABASE_URL="postgresql://postgres@/$database?host=$dir"
status=0
# At a terminal the command stays in the foreground, so that it can read (--pdb, breakpoint())
# and Ctrl-C reaches it directly. A TERM or HUP sent to this script alone then waits for the
# command to end, since bash runs a trap only between commands; it never cleans up under it.
if [ -t 0 ]; then
  trap : TERM HUP
  "$@" 8>&- 9>&- || status=$?
  exit "$status"
fi

# Otherwise in a process group of its own, so that a signal reaches all of it (pytest -n has
# workers) and the database is only dropped once the command has ended.
set -m
"$@" 8>&- 9>&- &
child=$!
set +m
for signal in INT TERM HUP; do
  trap 'kill -'"$signal"' -- "-$child" 2>/dev/null || true' "$signal"
done
while :; do
  status=0
  wait "$child" || status=$?
  kill -0 "$child" 2>/dev/null || break # else a signal woke the wait, and the command still runs
done
exit "$status"
