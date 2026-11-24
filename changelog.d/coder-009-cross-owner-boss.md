### Fixed

- hub: a boss of another owner than its agent gets only the agent's `session_paused`, as
  docs/api.md §6.2 says. `member_not_listening`, `session_model_changed`, `holder_stalled`,
  `claim_expired`, `member_availability_changed`, `cover_started`, `cover_ended` and the
  added recipient of a takeover's `member_joined` no longer reach such a boss, and the
  admins read `holder_stalled` and `claim_expired` as they do when the agent has no boss.
