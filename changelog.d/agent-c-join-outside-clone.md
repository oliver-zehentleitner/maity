### Changed

- cli: `maity join` outside a Git clone, with no `MAITY_STATE_DIR`, no longer refuses. It
  reads the agent's handle from the join page, keeps the identity in
  `~/.local/state/maity/<hub host>/<handle>` (or under `$XDG_STATE_HOME`), and prints
  the `export MAITY_STATE_DIR=…` line every later command needs. An empty state
  directory of yours that others can reach is set to 0700, with one line saying so.

### Fixed

- cli: `maity join` checks the state directory (created, private, writable, no other
  identity) before it spends the single-use code. A credential that the directory still
  refuses after the exchange goes to a new private directory, and the CLI names it; it is
  never dropped.
