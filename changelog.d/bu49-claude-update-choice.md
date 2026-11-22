### Added

- cli: `track` under `[harness.claude-code]` in runner.toml chooses which Claude Code
  version the runner's managed update takes. `"checked"`, the default, installs at most
  the version whose sandbox `maity` checked, never going back on its own from a newer
  one. `"newest"` takes every new release, as before. With `"newest"`, `maity runner
  check` and the runner's log name a version above the checked one as a note, not a
  warning. With `"checked"`, the warning names the way back (`maity runner tools
  rollback`). `maity runner tools` shows the newest release next to the held target.

### Changed

- cli: a runner that updates Claude Code no longer installs a release above the
  sandbox-checked version unless its configuration says `track = "newest"`.
