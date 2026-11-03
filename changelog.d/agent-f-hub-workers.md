### Added

- Hub: `MAITY_WORKERS` (chart `config.workers`) runs several serving processes per pod, 1–64,
  default 1. More than one only with PostgreSQL; the database pool stays the hub's total and is
  split among the processes. The request stats line names its process (`pid=`).
