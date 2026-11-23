### Added

- cli: `track` under `[harness.claude-code]` in runner.toml chooses which Claude Code
  version the runner's managed update takes. `"checked"`, the default, installs at most
  the version whose sandbox `maity` checked, never going back on its own from a newer
  one. `"newest"` takes every new release, as before. With `"newest"`, `maity runner
  check` and the runner's log name a version above the checked one as a note, not a
  warning. With `"checked"`, the warning names the way back (`maity runner tools
  rollback`, or installing the checked version by hand) in `check`, on ssh hosts and in
  the runner's log. `maity runner tools` shows the version the update is held at.

### Changed

- cli: existing runners with `update = "daily"` and no `track` now hold Claude Code at
  the sandbox-checked version and stop taking newer releases. A runner already above
  the checked version stays where it is and `maity runner check` warns until the checked
  version catches up. Set `track = "newest"` under `[harness.claude-code]` for the old
  behaviour.
