# Maintenance windows in the CLI

## `maity wait` sleeps a maintenance window out, every other command exits 7

**Id:** 8b94b16b-292e-4e3b-bc2a-c8058d7545ea
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** card tsk-12hwmpykz2ht (the project owner's design of 2026-11-02); docs/api.md §13, §16.12
**Revisit when:** the hub's `Retry-After` stops naming the end of the window, or agents run commands other than `wait` in a loop

On `503 maintenance` `maity wait` sleeps for `Retry-After` plus a random 0–60 seconds and reads on, never past
`--timeout` (exit 3 then, as any timeout), so a loop that re-arms it waits the window out without a change.
The jitter keeps every agent of a hub from calling in the same second the window ends. Every other command
prints when to try again and exits 7: its own code, so an agent's script tells a pause of the hub from an
error (1), and a wait loop that stops on anything but 0 and 3 is never hit by it.

**Rejected alternatives:**
- `wait` exiting 7 as well: every agent's loop would stop and need a human or a new rule to re-arm it.
- Retrying in every command: a command an agent runs once would hang for up to the whole window.
