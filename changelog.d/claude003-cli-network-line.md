### Fixed

- cli: an answer from the hub that breaks off (a status line, headers or body cut short) ends
  the `MAITY_ERROR_LINE` machine line with `network`, as a hub not reached does, instead of
  `-`, so the runner's `join_failed` detail names it; the message text is unchanged. `network`
  now comes from a flag the one transport-error mapping sets, no longer from the message's
  wording, and path segments and the signed query share one encoder.
