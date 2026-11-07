### Fixed

- cli: `maity report` without a working `gh` (missing, or its GraphQL refused,
  as in Claude Code cloud sessions) reads the pull request the card links
  through the hub's probe and reports it when its head is the pushed head;
  another head is refused with exit 4 (tsk-grk7tg5temyc).
