### Added

- hub: the request log ends in `ms=` (how long the hub took) and `route=` (the route's pattern), and once a minute a `stats` line gives the requests, the 5xx, the slowest request and the state of the connection pool, as `key=value` for `kubectl logs`
