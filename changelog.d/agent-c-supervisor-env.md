### Added

- cli: the runner puts `MAITY_SUPERVISOR=maity-runner/<version>` into every session it
  starts, and `maity resume` sends it as `supervisor` (§15.11). A value other than a
  runner's name is a usage error, and a hub without the field gets the resume without it.
