### Fixed

- cli: interactive opencode placements start again on OpenCode 2.3, whose TUI
  refuses `--model`: the runner names the model as the top-level `model` of the
  placement's own `opencode.json` instead, and starts the TUI with
  `--standalone` so that file and the switch that keeps the repository's own
  opencode configuration out apply to it, not to a shared background service.
  The runner still refuses a start whose model is missing or not among the
  configured `models`.
- cli: supervised opencode placements run `opencode run --model …` in the
  clone as the working directory; OpenCode 2.3's `run` has no `--dir`.

### Added

- cli: `maity runner check` reads `opencode --help` and `opencode run --help`
  and reports an error when a flag the runner's start passes in a configured
  mode is missing, before a placement crash-loops on it.
