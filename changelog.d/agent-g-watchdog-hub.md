### Added

- hub: the runner's placement read (`/runner/placements`, the `hello` packet, the answer
  to a status or workspace report) carries `session`: `started_at` of the newest session
  of the placement's credential, `not_listening_since` of the episode that runs now (§5.3),
  `paused` and `dormant`; `null` for a foreign placement. Computed at each read in a fixed
  number of statements per page; no event, no change of `seq` (§15.8).
- hub: a status report takes `finding` (§15.7): a cause, signals as fixed codes and the
  runner's own log lines, each list closed and the log bounded (200 lines, 1024 bytes of
  printable ASCII each, 24 KiB together); `invalid` names the field by its dotted path.
  `reported` keeps it as sent, `null` for a report without one. Its `log` is shown only to
  the runner's owner, the agent profile's owner and the project's members with trust
  `owner` or `admin`, never through a bridge; the `placement_reported` event carries the
  finding without `log`. The history (`…/reports`) holds no log lines yet.
- hub: `hung` takes the details `not_listening` and `never_joined` (§15.7, §15.14).
