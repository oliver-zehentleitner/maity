### Changed

- hub: `GET /projects/{owner}/{slug}/members` reads the member humans with the agents' owners, their
  pictures, the projects, the instances and the briefing writers once each instead of twice:
  40 → 35 statements per read on PostgreSQL.
