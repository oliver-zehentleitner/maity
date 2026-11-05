### Fixed

- CLI runner: files for the agents' side in the `agent_user` and `ssh` layouts are written without GNU `install -D`, with tools BSD, macOS and GNU all have, so a host whose `install` refuses `-D`, or gives it another meaning, can start agents. The file's own directory, if missing, is made 0700; a link at the path is replaced, a directory there is refused.
- CONTRIBUTING: the opt-in pre-push hook is not for a clone a maity runner manages, whose clone check refuses `core.hooksPath`.
