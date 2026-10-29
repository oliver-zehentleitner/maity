# Releases

## Readiness is recomputed inside every write that can change it; the announcement is a stored flag

**Id:** ffc30b1f-9412-45f7-94c7-b02c8552c0a7
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** implementation session, 2026-10-21 (the release and contract cards slice); accepted in the coordinator's two reviews of PR #30, the freeze at close decided there (2026-10-22)
**See:** https://github.com/oliver-zehentleitner/maity — 098ef90f-83b8-4b38-9c21-1e89c086b6db — as of 2026-10-21
**Revisit when:** the probe writes observations in the background (it must call the same recheck), or a project holds more than one open release

While a release is open, `readiness` is never stored: every read computes
it from the shipped cards, the observed forge state and the checklist.
`release_ready` must still fire once when it turns true, and a read must
not write. So every write that can change an input calls `releases.recheck`
in its own transaction: a card's creation (a release can be ready from the
start), its status, a report, a release `PATCH`, a checklist tick, and a
change of the project's repository. The release keeps `ready_announced`
in its data. The event goes out when computed readiness and the flag
differ in the direction of ready; a turn back resets the flag silently, so
a later turn to ready announces again.

The write that closes a release clears `release_in_flight`, so `recheck`
no longer finds it. That write calls `releases.close` instead. It
announces a release that this very write made ready, then freezes
`pull_requests`, `groups` and `readiness` into the card. A closed release
serves what was frozen: it is the record of what shipped, and later edges,
observations or cards do not change it (docs/api.md §6.7).

**Reason:** the event is written in the same transaction as the change
that caused it, so it is never lost and never doubled, and readiness on
the card cannot drift from what the reader computes.

**Rejected alternatives:**
- Storing readiness as a column: a second source of truth that every
  writer, the probe included, would have to keep in step with the
  computation.
- A background job comparing readiness periodically: a delay, a process
  to run, and a window in which the card says ready and nobody was told.

## The released mark is set where the probe stores a found tag, not in the release round

**Id:** 953b2971-7942-42b1-a71a-7ff9c688213b
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** implementation of `released_at` (card "hub: released_at for the launch state, its probe hook and the rules text"), 2026-10-29; contract in `docs/api.md` §6.1
**See:** https://github.com/oliver-zehentleitner/maity — de8abccf-94dc-4947-9926-463aa13edd8f — as of 2026-10-29

`probe.observe` sets `released_at` in the same transaction that stores a
tag observation with `found: true`, when the tag is `v<version>` of any
release card of the project, open, done or cancelled. Migration 0097
fills older projects from the stored tag observations. The cache keeps
only the latest read of each ref, so the time it takes is when the tag
was last seen, not when it was first found. No earlier time is recorded
anywhere.

**Reason:** the contract ties the mark to the first time the probe finds
a release tag, whether or not the release card is done. A tag can be read
by the release round, by `GET /probe?tag=` or after its card closed. Only
the one place every read passes through sees all of them.

**Rejected alternatives:**
- Setting it in `observe_release`, the open release's round: it never sees
  a tag read for a closed release or through `GET /probe`.
- Setting it when the release card moves to `done`: the contract says
  "whether or not the release card is `done` yet".
