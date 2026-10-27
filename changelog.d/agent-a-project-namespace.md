### Changed

- docs/api.md §6.25: projects live in their owner's namespace — every project route is
  `/projects/{owner}/{slug}/…`, the project carries `owner` and `full_name` (`oliver/maity`), and
  a slug is unique per owner only. A rename (`PATCH` `slug`) or a transfer
  (`POST …/transfer`, namespace owner, step-up) keeps the old full name as an alias that resolves
  everywhere (at most 8, `alias_limit`). Hub and CLI switch in one release; an older CLI gets
  `client_outdated` (426). The badge, the swarm page, the dashboard's `#/p/…` and the forge
  webhook keep their old addresses for existing projects. References shown outside a project
  read `<full_name>/<id>`.
