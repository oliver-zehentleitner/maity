### Changed

- web: a join line for another instance of an agent, or one that replaces an instance, comes after
  a note: every instance needs a state directory of its own, with the `export MAITY_STATE_DIR=…` to
  set in a clone where the agent already joined, and `maity resume` there takes over that instance.
- docs/agents.md: the same for the human, and the troubleshooting row for "already holds a session
  credential" no longer sends another instance to `maity resume`.
