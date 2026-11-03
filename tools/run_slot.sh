#!/usr/bin/env bash
# Runs a command in one of a few run slots shared by everyone on this machine:
#
#   tools/run_slot.sh make -C web smoke
#
# At most MAITY_RUN_SLOTS commands (default 2) hold a slot at a time; a further one waits,
# says so, and starts once a slot is free; it does not fail. hub/scripts/with_postgres.sh takes
# a slot by itself. The slots are lock files in MAITY_RUN_SLOTS_DIR (default
# ~/.local/state/maity/run-slots). PYTEST_XDIST_AUTO_NUM_WORKERS defaults to 2, so `pytest -n
# auto` starts two workers. Without flock (macOS) the command runs at once, without a slot.
set -euo pipefail

if [ "$#" -eq 0 ]; then
  echo "usage: $0 <command> [argument ...]" >&2
  exit 2
fi

export PYTEST_XDIST_AUTO_NUM_WORKERS="${PYTEST_XDIST_AUTO_NUM_WORKERS:-2}"

# A command started inside a slot (a smoke run that calls with_postgres.sh) keeps that slot.
if [ -n "${MAITY_RUN_SLOT:-}" ]; then
  exec "$@"
fi
if ! command -v flock >/dev/null; then
  echo "$0: flock not found; running without a slot" >&2
  export MAITY_RUN_SLOT=none
  exec "$@"
fi

slots="${MAITY_RUN_SLOTS:-2}"
case "$slots" in
  '' | *[!0-9]* | 0)
    echo "$0: MAITY_RUN_SLOTS must be a whole number of 1 or more, not '$slots'" >&2
    exit 2
    ;;
esac
dir="${MAITY_RUN_SLOTS_DIR:-${XDG_STATE_HOME:-$HOME/.local/state}/maity/run-slots}"
mkdir -p "$dir"
who="${MAITY_RUN_NAME:-${USER:-someone}}"

waited=""
start=$SECONDS
while :; do
  for ((i = 0; i < slots; i++)); do
    # Opened for appending, so that a failed try does not empty the file another run holds.
    exec 7>>"$dir/slot$i"
    if flock -n 7; then
      printf '%s (pid %s): %s\n' "$who" "$$" "$*" >"$dir/slot$i.who"
      if [ -n "$waited" ]; then
        echo "$0: got slot $i after $((SECONDS - start)) s" >&2
      fi
      # The command and everything it starts inherit fd 7: the slot is free once all of it ended.
      export MAITY_RUN_SLOT="$i"
      exec "$@"
    fi
    exec 7>&-
  done
  if [ -z "$waited" ]; then
    holders=""
    for ((i = 0; i < slots; i++)); do
      holders+="$(cat "$dir/slot$i.who" 2>/dev/null || true); "
    done
    echo "$0: all $slots run slots are taken (${holders%; }); waiting for one" >&2
    waited=1
  fi
  sleep 2
done
