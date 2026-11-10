### Changed

- hub: on PostgreSQL the bell's long-poll (§18.2) and the device-code waits no longer read the
  database every 0.5 s and 0.25 s: they wake on the events of the human's projects, on
  `maity_bell` for the human's own records and read marks and on `maity_device` for a code's
  changes, across replicas, and look again at the latest every 2 s; SQLite and MariaDB keep the
  polls (hub/context/replicas.md 387c2409, point 5).
