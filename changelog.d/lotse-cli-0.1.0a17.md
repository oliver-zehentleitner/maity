### Changed

- cli: version 0.1.0a17 for PyPI, a quick release for one runner fix: a Claude Code placement's
  sandbox starts again. 0.1.0a16 pointed `TMPDIR` into the placement scratch, which made the
  socket path Claude Code's sandbox binds there longer than the 107-byte Unix limit, so every
  sandboxed command failed with "Failed to create bridge sockets"; `TMPDIR` is now set there only
  when such a socket fits (#2014, tsk-55fahmskhq9f).
