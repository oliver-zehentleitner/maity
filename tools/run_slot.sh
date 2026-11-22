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
# So does it, with a warning and without a log line, when the slot directory or a slot file in it
# cannot be written (a sandboxed agent session may write only its clone and a few other places);
# MAITY_RUN_SLOTS_DIR can then point to a directory it may write.
#
# Each run that gets a slot appends a start line, and once its process is gone an end line, to
# $MAITY_RUN_SLOTS_DIR/log, tab-separated, the time in UTC:
#
#   start  2026-11-18T09:12:03Z  slot=0  pid=4711  wait=12  who=maity-coder#cbt4  cmd=make smoke-run
#   end    2026-11-18T09:14:41Z  slot=0  pid=4711  secs=158
#
# `wait` is the seconds spent waiting for a slot, `who` is MAITY_RUN_NAME (set it to
# handle#instance) or else the user name, `cmd` the program and its first argument only. The end
# line is written by a watcher that checks every second whether the command's process is gone; a
# process the command left running can hold the slot for longer than that. The watcher runs in a
# session of its own (setsid) and ignores INT, HUP and TERM, so cancelling the command's process
# group does not take it along; a KILL to the watcher or a reboot still does. So the log does not
# promise an end line for every run: a start line whose run is over and that has no end line
# (same slot and pid) means the run was aborted. The log is created readable by the account's
# group, writable by the account only. A log that is not a regular file (a FIFO, a directory) is
# skipped, and one that cannot be written is ignored: logging never holds up or stops a run.
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
# A slot directory or slot file this run may not write: the command runs without a slot, as without
# flock, rather than not at all. Failing made sandboxed agents skip the slot (`make smoke SLOT=`),
# and then their runs were not logged either.
no_slot() { # <path that cannot be written> <command> [argument ...]
  echo "$0: cannot write $1; running without a slot and without a log line" \
    "(MAITY_RUN_SLOTS_DIR can point to a directory this run may write)" >&2
  shift
  export MAITY_RUN_SLOT=none
  exec "$@"
}
mkdir -p "$dir" 2>/dev/null || no_slot "$dir" "$@"
who="${MAITY_RUN_NAME:-${USER:-someone}}"
log="$dir/log"
# What the log and the slot's .who file name of the command: the program and its first argument
# (`pytest -n`, `make smoke`), enough to tell the runs apart for measuring them.
cmd="$1${2+ $2}"

# One printf per line onto a file opened for appending: a short line is one write, so the lines of
# runs that log at the same moment do not interleave. Created 0640: every run that writes it is
# the account's own, and its group may read it for measuring. A failure is ignored. Only a regular
# file, or none yet, is opened: opening a FIFO without a reader for appending would block, and
# with it the run that holds its slot. (The directory is the account's own, so the gap between
# check and open is no one else's to use.)
log_line() {
  [ -f "$log" ] || [ ! -e "$log" ] || return 0
  { (umask 027 && printf '%s\n' "$1" >>"$log"); } 2>/dev/null || true
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
    # `command` keeps a failed open from ending the script, even in POSIX mode (POSIXLY_CORRECT),
    # where a failed redirection on the special builtin exec would end it before the command ran.
    if ! { command exec 7>>"$dir/slot$i"; } 2>/dev/null; then
      no_slot "$dir/slot$i" "$@"
    fi
    if flock -n 7; then
      # The holder's name is for the waiting runs' message only; one that cannot be written
      # (a read-only directory with slot files from before) does not stop the run.
      { printf '%s (pid %s): %s\n' "$who" "$$" "$cmd" >"$dir/slot$i.who"; } 2>/dev/null || true
      if [ -n "$waited" ]; then
        echo "$0: got slot $i after $((SECONDS - start)) s" >&2
      fi
      pid=$$ # the command's, too: exec keeps it
      log_line "$(printf 'start\t%s\tslot=%s\tpid=%s\twait=%s\twho=%s\tcmd=%s' \
        "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$i" "$pid" "$((SECONDS - start))" \
        "$(one_field "$who" 64)" "$(one_field "$cmd" 200)")"
      # The watcher for the end line: started twice removed, so it is no child of the command (a
      # command that waits for all its children would wait for it too), without fd 7 (it would
      # hold the slot) and without the run's output (a reader would wait for its end). It ignores
      # INT, HUP and TERM from the start: the outer subshell ignores them before it forks the
      # watcher, so the watcher has them ignored before the command is exec'd and no group signal
      # can come first (an ignored signal stays ignored across fork and exec). It runs in a
      # session of its own, so a supervisor that cancels the command's process group does not
      # cancel the watcher, and the run keeps its end line. setsid execs at once here: the
      # subshell is no process group leader (no job control), and without --wait it never waits.
      # Without setsid the watcher stays in the command's group, still ignoring those signals.
      (
        trap '' INT HUP TERM
        (
          exec 7>&- </dev/null >/dev/null 2>&1
          watcher="$(declare -f log_line)"'
            log=$1 slot=$2 pid=$3
            began=$SECONDS
            while kill -0 "$pid" 2>/dev/null; do sleep 1; done
            log_line "$(printf "end\t%s\tslot=%s\tpid=%s\tsecs=%s" \
              "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$slot" "$pid" "$((SECONDS - began))")"'
          set -- "$BASH" -c "$watcher" run_slot-watcher "$log" "$i" "$pid"
          if command -v setsid >/dev/null; then
            set -- setsid "$@"
          fi
          exec "$@"
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
      # A holder that could not write its .who (a read-only directory) leaves it empty or missing.
      holder="$(cat "$dir/slot$i.who" 2>/dev/null || true)"
      holders+="${holder:-unknown}; "
    done
    echo "$0: all $slots run slots are taken (${holders%; }); waiting for one" >&2
    waited=1
  fi
  sleep 2
done
