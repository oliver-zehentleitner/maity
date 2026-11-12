### Added

- cli: `maity runner serve` notices an interactive agent that stopped listening. When no process runs below the
  harness (no `maity wait`, no tool) and the pane is unchanged for 30 minutes, it types one line into the pane
  telling the agent to go back to its wait loop, but only while no client is attached. Any answer counts. If the
  session does not react at all within 10 minutes, or the agent answered three such lines without going back to
  its wait, it ends the session, reports `exited`/`hung`/`idle` and starts it again; Claude Code resumes its last
  conversation (`--continue`). Five such ends in a row, with no `maity wait` in between, hold the placement as `failed`/`hung`. Before this, an agent whose wait ended (a full disk,
  a provider limit) sat idle while its placement showed `running`.
- contract: §15.14, the runner's own check of an interactive session, with or without the hub's ask.
- hub: a status report may carry `reason: hung` with `exited` or `failed`, and `detail: idle` or `tool` (§15.7).
