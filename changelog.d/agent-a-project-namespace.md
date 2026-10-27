### Changed

- docs/api.md §6.25: projects live in their owner's namespace — every project route is
  `/projects/{owner}/{slug}/…`, the project carries `owner` and `full_name` (`oliver/maity`), and
  every project reference, key and input outside the project uses `full_name`. A slug is unique
  per owner and never a route word (`reserved`); dashboard route words are reserved as handles.
  A rename (`PATCH` `slug`) or a transfer (`POST …/transfer`: namespace owner, step-up, the
  receiver's consent) keeps the old full name as an alias that is never given away (at most 8,
  `alias_limit`); the namespace owner cannot be demoted, removed or deleted (`namespace_owner`).
  Hub and CLI switch in one release; an old route gets `client_outdated` (426, old CLI) or
  `project_path_outdated` (410). The badge, the swarm page, the dashboard's `#/p/…` and the forge
  webhook keep their old addresses for existing projects without becoming an existence oracle.
