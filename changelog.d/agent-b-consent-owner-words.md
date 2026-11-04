### Fixed

- web: a change of another owner's agent that waits for its owner's consent (docs/api.md §6.2) names
  that owner in the members view's status line, not the raw `human:<id>`, and where part of the
  change applied at once (its `reports_to`) the line says what was saved and what still waits.
