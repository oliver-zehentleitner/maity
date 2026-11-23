### Changed

- cli: internal clean-up with no change in behaviour (audit round 5, batch 3): the Keep the
  Why skill's names, bounds, copy key and bounded file read live once in `skillop`, which
  `skills` imports; `skillop.put` opens its staged directories through `_open_up`, which
  fails on a directory it cannot open, as `_stage_and_replace` already did; a Codex
  placement's skill is written and cleared through `scratch`, anchored as its other
  CODEX_HOME files are; `maity gh pr edit` gets the pull request's number from where it
  built the call, and gh's JSON answers are read by one helper; `maity runner gc` reads the
  active placements one way whatever it removes; `--hub` against the clone's stored hub is
  decided by one function for every command and for `maity help`.
