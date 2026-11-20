### Changed

- contract: the runner's watch. Past a grace for a session that stopped listening, or
  without a join after a start, the runner diagnoses the placement, names one cause and
  reacts by it: one restart that resumes the session, a nudge, a wait for the limit's
  reset, or `failed` at once for a login or a refused pickup; a second failure within its
  window holds the placement as `failed`/`hung`. Paused and dormant agents are left alone.
  Not built yet (docs/api.md §15.14, tsk-twmms66p1ww4).
- contract: the runner's placement read carries `session` (`started_at`,
  `not_listening_since`, `paused`, `dormant`) for placements of the runner owner's own
  agents, `null` for a foreign one (req-1kk6pwdxdmg6). Not built yet (§15.8).
- contract: a status report may carry `finding`: a cause and signals as fixed codes, never
  pane text, a path or a secret, plus the runner's own last log lines about the placement,
  bounded and read only by the runner's owner, the agent's owner and the project's admin
  agents; `hung` gains the details `not_listening` and `never_joined`. Not built yet
  (§15.7).
- contract: the runner settings `[limits.watch]` `not_listening_grace_minutes`,
  `join_within_minutes`, `auto_restarts` and `retry_window_minutes`. Not built yet
  (docs/runners.md).
