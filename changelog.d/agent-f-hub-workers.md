### Added

- Hub: `MAITY_WORKERS` (chart `config.workers`) runs several serving processes per pod, 1–64,
  default 1. More than one only with PostgreSQL; the database pool stays the hub's total and is
  split among the processes, at least two connections each. The one-time work of a start runs in
  the parent; a worker that cannot start stops the supervisor. The request stats line names its
  process (`pid=`).

### Fixed

- Hub: a start renders the public pages again in place instead of clearing them first, so other
  processes and pods serving meanwhile never find a page missing; two pods starting together
  render a page and record the sign-in switch one after the other. An isolation ends the agent's
  waits held by other processes at their next read.
