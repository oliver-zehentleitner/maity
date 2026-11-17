#!/usr/bin/env bash
# Runs a command in one of a few run slots shared by every run of this account (the slots are
# files under its home, so another account has slots of its own):
#
#   tools/run_slot.sh make -C web smoke
#
# At most MAITY_RUN_SLOTS commands (default 2) hold a slot at a time; a further one waits,
# says so, and starts once a slot is free; it does not fail. hub/scripts/with_postgres.sh takes
# a slot by itself. The slots are lock files in MAITY_RUN_SLOTS_DIR (default
# ~/.local/state/maity/run-slots). PYTEST_XDIST_AUTO_NUM_WORKERS defaults to 2, so `pytest -n
# auto` starts two workers. Without flock (macOS) the command runs at once, without a slot.
#
# Each run that gets a slot appends two lines to $MAITY_RUN_SLOTS_DIR/log, tab-separated, the
# time in UTC:
#
#   start  2026-11-18T09:12:03Z  slot=0  pid=4711  wait=12  who=maity-coder#cbt4  cmd=make smoke-run
#   end    2026-11-18T09:14:41Z  slot=0  pid=4711  secs=158
#
# `wait` is the seconds spent waiting for a slot, `who` is MAITY_RUN_NAME (set it to
# handle#instance) or else the user name, `cmd` the command, cut at 200 characters. The end line is
# written by a watcher that checks every second whether the command's process is gone; a process
# the command left running can hold the slot for longer than that. A log that cannot be written
# never stops a run.
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
  '' | *[!0-9]* | 0*)
    echo "$0: MAITY_RUN_SLOTS must be a whole number of 1 or more without a leading 0, not '$slots'" >&2
    exit 2
    ;;
esac
dir="${MAITY_RUN_SLOTS_DIR:-${XDG_STATE_HOME:-$HOME/.local/state}/maity/run-slots}"
mkdir -p "$dir"
who="${MAITY_RUN_NAME:-${USER:-someone}}"
log="$dir/log"

# One printf per line onto a file opened for appending: a short line is one write, so the lines of
# runs that log at the same moment do not interleave. Group-writable when this creates it, as the
# directory is shared by the account's runs. A failure is ignored.
log_line() {
  { (umask 002 && printf '%s\n' "$1" >>"$log"); } 2>/dev/null || true
}
one_field() { # tabs and line breaks become spaces, so a field stays one field on one line
  local value="${1//[$'\t\n\r']/ }"
  printf '%s' "${value:0:$2}"
}

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
      pid=$$ # the command's, too: exec keeps it
      log_line "$(printf 'start\t%s\tslot=%s\tpid=%s\twait=%s\twho=%s\tcmd=%s' \
        "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$i" "$pid" "$((SECONDS - start))" \
        "$(one_field "$who" 64)" "$(one_field "$*" 200)")"
      # The watcher for the end line: started twice removed, so it is no child of the command (a
      # command that waits for all its children would wait for it too), without fd 7 (it would
      # hold the slot) and without the run's output (a reader would wait for its end).
      (
        (
          exec 7>&- </dev/null >/dev/null 2>&1
          trap '' INT HUP
          began=$SECONDS
          while kill -0 "$pid" 2>/dev/null; do sleep 1; done
          log_line "$(printf 'end\t%s\tslot=%s\tpid=%s\tsecs=%s' \
            "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$i" "$pid" "$((SECONDS - began))")"
        ) &
      )
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
