### Added

- hub: a project's rename (`PATCH /projects/{owner}/{slug}` with `slug`, by a human owner) and
  transfer to another namespace owner (`POST /projects/{owner}/{slug}/transfer`, a consent
  request the receiver answers), each keeping the full name given up as an alias (§6.25); the
  project view carries `aliases`. At most 8 aliases (`alias_limit`) and 3 renames and transfers
  per 24 hours (`rate_limited`); a stale `go` on a transfer is `invalid_transition`
  (`transfer_stale`) or `taken` and withdraws the request
- hub: ticker items of type `rename` (`<old> is now <new>`, audience `all`, written with the
  ticker off too)

### Changed

- hub: a project's namespace owner can no longer be demoted below owner or removed from the
  project (`namespace_owner`, 409)
