### Fixed

- hub: two simultaneous waits of one key on PostgreSQL no longer both end as superseded: the newer start decides, also inside a process.
