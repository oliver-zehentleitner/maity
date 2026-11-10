### Added

- hub: `MAITY_ROUTE_LIMITS` sets limits on single routes of the API for an
  emergency, `<METHOD> <route> = <count>/<seconds>`, counted per client address
  in each process; past one the call is `rate_limited` before its body is read.
  A route the hub does not have stops it at the start (docs/api.md §1.7).
- hub: `MAITY_PUBLIC_PAGE_LIMIT` and `MAITY_BADGE_LIMIT` set the read limits of
  the public pages and the badges, 60 per minute per address by default.
