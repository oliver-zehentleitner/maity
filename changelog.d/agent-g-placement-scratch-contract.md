### Added

- contract: a placement's scratch (docs/api.md §15.5): a directory per placement beside
  its clone, `<workspaces>/<project_id>/.scratch/<placement id>`, passed to a Claude Code
  or Codex session as `MAITY_SCRATCH` with `TMPDIR` inside it, for a review's or a test's
  leftovers; other harnesses get none until their sandbox is shown to write it. The
  runner removes it when the placement closes and after a stop on the clone's clock,
  only the path it built and never through a link; `maity runner gc --scratch` removes
  what no active placement names. Nothing in it is kept as unsaved work, and it is not
  reported to the hub. Removal after a stop comes with the clone's retention clock.
