### Fixed

- hub tests: the wake-up tests count only their own projects' wake-ups, so a notice another
  writer sends to the same database meanwhile no longer fails them (hub-postgresql flake seen
  on #619).
