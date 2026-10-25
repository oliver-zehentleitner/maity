### Fixed

- hub: a stopping hub answers its open events and runner long-polls at
  once (empty, not superseded) and bounds the graceful shutdown to 10
  seconds; an upgrade's old pod stopped after up to a minute of waiting
  for long-polls, and now stops in about a second.
