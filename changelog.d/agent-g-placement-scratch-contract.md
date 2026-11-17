### Added

- contract: a placement's scratch (docs/api.md §15.5): a directory per placement beside
  its clone, `<workspaces>/<project_id>/.scratch/<placement id>`, passed to the session as
  `MAITY_SCRATCH` with `TMPDIR` inside it, for a review's or a test's leftovers. The
  runner removes it when the placement closes and after a stop on the clone's clock;
  nothing in it is kept as unsaved work, and it is not reported to the hub. The runner's
  side is not built yet.
