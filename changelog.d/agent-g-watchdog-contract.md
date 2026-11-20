### Changed

- contract: the runner's watch. Past a grace for a session that stopped listening, or
  without a join after a start, the runner diagnoses the placement, names one cause and
  reacts by it: one restart that resumes the session, a nudge, a wait for the limit's
  reset, or `failed` at once for a login or a refused pickup; a second failure within its
  window, for the causes it restarts for, holds the placement as `failed`/`hung`. A pane
  match alone decides neither a login nor a limit. It ends no session a client is attached
  to, nudges once per episode, and reports a refused pickup at the refusal. Paused and
  dormant agents are left alone. Not built yet (docs/api.md §15.14, tsk-twmms66p1ww4).
- contract: the runner's placement read carries `session` (`started_at`,
  `not_listening_since`, `paused`, `dormant`) for placements of the runner owner's own
  agents, `null` for a foreign one (req-1kk6pwdxdmg6). Not built yet (§15.8).
- contract: a status report may carry `finding`: a cause and signals as fixed codes, never
  pane text, a path or a secret, plus the runner's own last log lines about that placement
  alone, in its own words with values from the agents' side as placeholders, bounded and
  read only by the runner's owner, the agent's owner and the project's members with trust
  `owner` or `admin`, never through a bridge or in an event; a log line in the credential
  format is refused with the report (`credential_in_payload`); `hung` gains the details
  `not_listening` and `never_joined`. Not built yet (§15.7, §15.5, §15.10, §8.2).
- contract: the runner settings `[limits.watch]` `not_listening_grace_minutes`,
  `join_within_minutes`, `auto_restarts` and `retry_window_minutes`. Not built yet
  (docs/runners.md).
