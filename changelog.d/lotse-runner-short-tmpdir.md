### Fixed

- runner: a Claude Code placement's sandbox starts again. Since 0.1.0a16 the runner pointed
  `TMPDIR` into the placement scratch, and under a deep workspaces root the path of the socket
  Claude Code's sandbox binds there was longer than the 107-byte Unix socket limit, so every
  sandboxed command failed with "Failed to create bridge sockets". The runner now sets `TMPDIR`
  only when such a socket fits; otherwise the session keeps the host's `TMPDIR` and
  `MAITY_SCRATCH` still names the scratch (tsk-55fahmskhq9f).
