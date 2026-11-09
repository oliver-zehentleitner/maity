### Changed

- hub: a signed-in human's call reads its session and account once, and the sign-in policy once,
  before the route runs: four statements fewer on every dashboard call (members 44 → 40, project
  29 → 25, tasks 24 → 20, sessions 17 → 13 on PostgreSQL).
