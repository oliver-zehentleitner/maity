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

### Security

- cli: the launch preparation writes a Codex placement's control files only
  below the scratch it created, never through a link, so they cannot be
  redirected outside it.
- cli: a Codex placement's sandbox profile gives its `CODEX_HOME` to the
  sandboxed commands as read-only, so a session may read its own
  configuration but cannot rewrite the control files a later restart reads.
