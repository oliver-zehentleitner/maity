### Fixed

- cli: a Codex placement puts `CODEX_HOME` inside the placement scratch, under
  the workspaces root, instead of the runner's state directory. The codex
  sandbox hides the state directory, so a Codex placement there could not run
  any command and `maity resume` never started; beside the scratch the sandbox
  re-opens it, while it stays hidden from every other placement.

### Added

- cli: `maity runner check` reports an error when a Codex placement's
  `CODEX_HOME` would fall under a path the codex sandbox hides, before a
  placement starts.
