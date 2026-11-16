### Changed

- runner: the sandbox-checked Claude Code version is raised to 2.1.325, so
  `maity runner check` no longer warns about it; verified by a static read
  that a command with something in front of `maity` stays sandboxed.
