### Fixed

- CLI runner: files for the agents' side in the `agent_user` and `ssh` layouts are written with POSIX tools only, so a host whose `install` has no `-D` (BSD, macOS) can start agents. A missing directory for such a file is made 0700.
