### Changed

- hub: on PostgreSQL whether an agent or a runner is listening (presence, team wakes, the jour
  fixe, statistics, badges) holds across replicas: every open long-poll is a row of the UNLOGGED
  table `long_poll`, and each hub process keeps a heartbeat in `hub_pod`; a wait of a process not
  seen for 45 s does not count. SQLite and MariaDB keep the registry in the process
  (hub/context/replicas.md 387c2409, point 4).
