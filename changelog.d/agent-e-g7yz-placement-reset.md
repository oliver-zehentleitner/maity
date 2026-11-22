### Added

- hub: a reset of a placement, `POST …/placements/{id}/restart` with `fresh_session: true`: a
  restart whose new generation starts the agent on a fresh harness session instead of resuming
  the last one; the placement carries `fresh_session` while that generation is current, and a
  runner's report takes `sessions`, the fresh sessions of its generation (docs/api.md §15.5–§15.7,
  §15.14; tsk-r4apvj4kbf3a).
- runner: a reset's generation starts Claude Code, Antigravity, Codex and opencode on a fresh
  session, never resuming the last conversation, logs it as a reset, and reports `sessions` to a
  hub whose placements carry `fresh_session` (tsk-r4apvj4kbf3a).
- web: **Reset** next to **Restart** on a managed agent's row, confirmed with one more click that
  says the running conversation is dropped and the clone and its branches stay; the generation
  a reset made reads "a fresh session" (tsk-r4apvj4kbf3a).
