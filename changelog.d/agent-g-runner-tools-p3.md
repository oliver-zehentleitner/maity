### Fixed

- CLI: a runner tool install that breaks off midway (a download cut
  short, an installer error of any kind) now ends as `failed` and
  leaves nothing half-installed, instead of staying `installing` and
  downloading again every minute.
- CLI: an "Update now" for a tool the runner may not install
  (`install = false`, tool missing) is reported as settled at once, so
  the hub no longer keeps it standing.
- CLI: a placement starts with the tool binary and sandbox setting its
  start check approved, even if a rollback swaps the tool in between.
