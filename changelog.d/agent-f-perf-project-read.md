### Changed

- hub: `GET /projects/{owner}/{slug}` resolves the project, the caller's membership and the owner's
  handle once instead of three times: 25 → 17 statements per read on PostgreSQL.
