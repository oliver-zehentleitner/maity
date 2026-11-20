### Changed

- cli: a Claude Code or Codex placement whose scratch leaves no room for a Unix
  socket under its `tmp` (the usual case under the default `~/maity-workspaces`)
  gets a short `TMPDIR` of its own again: `tmp` in a fresh 0700 leaf under the
  per-user `/tmp/maity-scratch-<uid>` parent, opened again in its sandbox for it
  alone and removed when the placement closes. Before, such a session had no
  `TMPDIR`, and its temporary files went to the shared `/tmp`.
