### Changed

- cli: a Claude Code placement whose scratch leaves no room for a Unix socket
  under its `tmp` (the usual case under the default `~/maity-workspaces`) now
  gets the same short 0700 leaf under the per-user `/tmp/maity-scratch-<uid>`
  parent that a Codex placement gets, as its `CLAUDE_CODE_TMPDIR`. Claude
  Code's own temporary files and its sandbox socket go there, removed when
  the placement closes, instead of in the `/tmp/claude-<uid>` directory every
  Claude Code session of that user shares.
