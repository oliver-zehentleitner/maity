### Added

- docs/api.md §5.3: a model change is a new session; a resume whose model or harness differs from
  the instance's previous session emits `session_model_changed` to the agent's lead and the
  admins. Rule 14 in the agent skill and docs/agents.md: resume with the new model at once.
