### Added

- CLI: the runner installs Claude Code and Codex and keeps them current
  where its configuration says so (`install = true`, `update = "daily"`
  under `[harness.<id>]`): the exact vendor release, checked against
  Claude Code's signed manifest or Codex's SHA-256 before use, beside the
  version in use and never under a running session; `maity runner tools`
  lists the versions and `maity runner tools rollback <tool>` goes back.
  The runner reads the owner's "Update now", reports
  `capabilities.tools`, and reports a tool without a login as
  `login_needed`.

### Changed

- CLI: `[maity] update` is refused by `check` and `serve` until the
  runner carries it out.
- Docs: Claude Code runs without its sandbox outside Linux and macOS, or
  on Linux without bwrap and socat (it said "off Linux").
