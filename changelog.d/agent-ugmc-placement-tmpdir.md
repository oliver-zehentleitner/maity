### Changed

- cli: a Codex placement whose scratch leaves no room for a Unix socket under
  its `tmp` (the usual case under the default `~/maity-workspaces`) gets a short
  `TMPDIR` of its own again: `tmp` in a fresh 0700 leaf under the per-user
  `/tmp/maity-scratch-<uid>` parent, opened again in its sandbox for it alone
  and removed when the placement closes. Claude Code placements keep starting
  without a `TMPDIR`, since Claude Code's sandbox mounts such a leaf read-only.
- cli: a `/tmp` leaf a restart fails to remove (agy's scratch included) is kept
  on record and removed at a later start or at the close, instead of being left
  behind.
