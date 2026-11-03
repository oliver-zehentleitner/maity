### Added

- Chart: `replicas` (default 1) runs several hub pods on PostgreSQL. More than one rolls one pod
  at a time, gets a PodDisruptionBudget and spreads over nodes (`topologySpreadConstraints`);
  one replica keeps `Recreate`. `database.poolSize` and `.maxOverflow` set each pod's pool.
- Hub: `MAITY_REPLICAS` (set by the chart) refuses more than one replica off PostgreSQL or with a
  local attachment directory, and the hub warns at its start when the connections it may ask
  (per worker its pool and overflow share and a listener, per pod one for the probe, for
  replicas + 1 pods during a rolling update) exceed what PostgreSQL gives ordinary roles.
