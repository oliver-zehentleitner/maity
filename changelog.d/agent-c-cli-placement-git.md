### Changed

- CLI: in a session the runner started (`MAITY_PLACEMENT`), maity runs git only in the
  runner's clone (the parent of `GIT_COMMON_DIR`), only from a directory inside it, and only
  while that clone is laid out and configured like a plain clone, the check `gc` already
  makes (now shared in `maity.clonecheck`); git is pinned to that clone. Outside a placement
  nothing changes.

### Fixed

- CLI runner: `gc` reads a clone's configuration the way git does, and accepts a branch or
  remote whose name holds a dot.
