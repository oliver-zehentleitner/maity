### Added

- Chart: `replicas` (default 1) runs several hub pods on PostgreSQL. More than one rolls one pod
  at a time, gets a PodDisruptionBudget and spreads over nodes (`topologySpreadConstraints`);
  one replica keeps `Recreate`. `database.poolSize` and `.maxOverflow` set each pod's pool.
- Hub: `MAITY_REPLICAS` (set by the chart) refuses more than one replica off PostgreSQL or with a
  local attachment directory, and the hub warns at its start when replicas × (pool + overflow +
  workers + 1) exceeds what PostgreSQL gives ordinary roles.
