### Added

- hub: `session_model_changed` when a resume's harness or model differs from the
  instance's previous session; it wakes only the member the agent reports to (§5.3).

### Fixed

- hub: a resume that omits `model` keeps the previous session's model instead of clearing it
  (§5.3).
