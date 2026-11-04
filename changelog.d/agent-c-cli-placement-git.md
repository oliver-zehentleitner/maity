### Changed

- CLI: in a session the runner started (`MAITY_PLACEMENT`), maity runs git only in the
  runner's clone (the parent of `GIT_COMMON_DIR`), only from a directory inside it, and only
  while that clone is laid out and configured like a plain clone, the check `gc` already
  makes (now shared in `maity.clonecheck`). Each such git reads a repository maity writes
  for that run under the clone's `.git/maity`, with a configuration of maity's own and the
  clone's checked entries passed on; objects, index and work tree stay the clone's, and
  `status` writes nothing into it. The state directory there is the clone's `.git/maity`,
  found without git. Outside a placement nothing changes.
- CLI README: the git of the harness and of other programs in the clone is not covered by
  maity's checks.

### Fixed

- CLI runner: `gc` reads a clone's configuration the way git does, and accepts a branch or
  remote whose name holds a dot, and a clone made by git for Windows.
