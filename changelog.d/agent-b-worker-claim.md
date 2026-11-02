### Changed

- Hub: with several replicas on PostgreSQL, each worker's pass runs once per interval, in whichever
  process claims it first in `worker_run`; two processes counting the same minute of presence no
  longer collide. The request stats reporter stays per process.

### Fixed

- Help: `probe_observed` is described with its real condition, not "while the card is open".
