### Added

- hub: the once-a-minute statistics name the slow routes: up to ten `stats_route` lines per pod with the route's pattern, its requests, how many took 1 s and 3 s or more, total and maximum time; the `stats` line gains `slow_routes`; a held long-poll does not count for its route
