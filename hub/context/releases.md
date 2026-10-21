# Releases

## Readiness is recomputed inside every write that can change it; the announcement is a stored flag

**Id:** ffc30b1f-9412-45f7-94c7-b02c8552c0a7
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** implementation session, 2026-10-21 (the release and contract cards slice)
**See:** https://github.com/oliver-zehentleitner/maity — 098ef90f-83b8-4b38-9c21-1e89c086b6db — as of 2026-10-21
**Revisit when:** the probe writes observations in the background (it must call the same recheck), or a project holds more than one open release

`readiness` is never stored: every read of a release computes it from the
shipped cards, the observed forge state and the checklist. `release_ready`
must still fire once when it turns true, and a read must not write. So
every write that can change an input — a card's status, a report, a
release `PATCH`, a checklist tick — calls `releases.recheck` in its own
transaction, and the release keeps `ready_announced` in its data. The
event goes out when computed readiness and the flag differ in the
direction of ready; a turn back resets the flag silently, so a later turn
to ready announces again.

**Reason:** the event is written in the same transaction as the change
that caused it, so it is never lost and never doubled, and readiness on
the card cannot drift from what the reader computes.

**Rejected alternatives:**
- Storing readiness as a column: a second source of truth that every
  writer, the probe included, would have to keep in step with the
  computation.
- A background job comparing readiness periodically: a delay, a process
  to run, and a window in which the card says ready and nobody was told.
