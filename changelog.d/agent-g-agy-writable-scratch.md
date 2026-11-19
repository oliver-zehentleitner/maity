### Added

- cli: an antigravity placement gets a scratch, so an agy reviewer can write
  its `review_result` file and name it with
  `maity say --review-file "$MAITY_SCRATCH/review.json"`. Its sandbox makes the
  beside-clone `.scratch` read-only, so the scratch goes under the host's
  shared temporary directory instead, in a per-user parent owned 0700 by the
  user the agents run as, with a per-placement directory inside it. The
  per-placement name is recorded so the session and the runner find it again
  across a restart and on close. It is emptied and remade at every start, so
  nothing in it survives a restart, and it is removed cleanly even when it
  holds a read-only directory a build tool left. The session reaches it as
  `MAITY_SCRATCH`, with `TMPDIR` inside it, and the file is read through the
  existing recorded-scratch path, whose root is resolved so a shared temporary
  directory that is itself a link still works. The scratch is separated against
  other host users and against the sandboxed Codex and Claude Code placements
  of that user (their sandbox is told to hide the per-user parent), but not
  against other agy or unsandboxed placements of the same host user; that
  same-user exposure is accepted until each placement runs as its own user
  (`tsk-bbhcekjk2mgm`). An agy placement on an ssh host still gets none.
