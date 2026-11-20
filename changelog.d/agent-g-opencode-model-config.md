### Fixed

- cli: interactive opencode placements start again on OpenCode 2.3, whose TUI
  refuses `--model`: the runner names the model as the top-level `model` of the
  placement's own `opencode.json` instead (supervised `opencode run` keeps
  `--model`), and still refuses a start whose model is missing or not among the
  configured `models`.

### Added

- cli: `maity runner check` reads `opencode --help` and `opencode run --help`
  and reports an error when a flag the runner's start passes in a configured
  mode is missing, before a placement crash-loops on it.
