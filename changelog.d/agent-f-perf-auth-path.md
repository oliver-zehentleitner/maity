### Changed

- hub: a call with a completed dashboard sign-in reads its session and account in one standalone
  SELECT, after its own presence writes, and the sign-in policy once, before the route runs: four
  statements fewer per call on the measured routes (members, project, tasks, sessions on
  PostgreSQL), three on a session that still owes its TOTP code.
