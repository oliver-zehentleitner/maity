### Fixed

- Hub tests: the tests that say a call costs the same statements for more rows no longer fail at random on PostgreSQL. They count only the statements of the measured call, in every thread its request hands work to, and not those of a background worker that ticked during it (tsk-dbnh1nhcjrc4).
