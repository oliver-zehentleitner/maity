### Added

- cli: `maity runner serve` notices an interactive agent that stopped listening. When no `maity wait` runs below its
  pane and the pane is unchanged for `hang_after_minutes` (default 30), it types one line into the pane telling
  the agent to go back to its wait loop, but only while no client is attached. If still nothing after
  `reply_within_minutes` (default 10), it ends the session, reports `exited`/`hung`/`idle` and starts it again;
  Claude Code resumes its last conversation (`--continue`). Before this, an agent whose wait ended (a full disk,
  a provider limit) sat idle while its placement showed `running`.
- contract: §15.14, the runner's own check of an interactive session, with or without the hub's ask.
- hub: a status report may carry `reason: hung` with `exited` or `failed`, and `detail: idle` or `tool` (§15.7).
