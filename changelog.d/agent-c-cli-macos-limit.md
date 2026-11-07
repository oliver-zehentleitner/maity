### Fixed

- CLI runner: in the `agent_user` and `ssh` layouts, the exit code of a provider limit is read from the agents' side by the runner's own module (`maity runner limitread`), not by `dd`, whose macOS version has no `iflag`. On macOS hosts the limit now keeps its exit code. A host whose `maity` is older records the limit without an exit code. The file is still read only as a regular file, never through a link or from a FIFO.
- CLI tests: the `agent_user` prerequisites test is skipped with its reason when `maity` is not installed for the interpreter (`-I` ignores `PYTHONPATH`), and the sandbox test expects Claude Code's sandbox only on Linux.
