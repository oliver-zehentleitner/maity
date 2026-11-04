### Changed

- CLI: in a session the runner started, each git maity runs reads a repository maity writes
  for that run under the clone's `.git/maity`, with a configuration of maity's own and the
  clone's checked entries passed on, instead of the clone's `.git`; objects, index and work
  tree stay the clone's, and `status` writes nothing into it. The state directory there is
  the clone's `.git/maity` without asking git.
- CLI README: the git of the harness and of other programs in the clone is not covered by
  maity's checks.
