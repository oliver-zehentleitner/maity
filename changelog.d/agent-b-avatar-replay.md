### Fixed

- hub: `DELETE /agents/{id}/avatar` checks that the caller still owns the profile before it
  replays a stored answer: a repeat of an old change with the same `Idempotency-Key` no
  longer shows the current picture state to someone who lost the agent (§6.10)
