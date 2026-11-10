### Fixed

- hub: a placement for an existing member answers `invalid` with `agent.id: not_yours` unless the
  calling human owns that agent's profile, or, for an agent's proposal, its own human does
  (docs/api.md §15.6).
