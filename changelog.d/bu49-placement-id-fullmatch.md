### Fixed

- cli: the runner matches the ids in a placement, a status file or an operator's
  argument in full (placement id, project, clone, harness), so an id with a
  trailing newline is refused. The scratch takes the placement id pattern from
  `clonecheck` instead of keeping its own copy.
