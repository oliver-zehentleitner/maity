### Added

- hub: `PATCH /orgs/{org}` takes `handle`, under every rule of a human's rename: the old handle stays as an alias, which `{org}`, `owner` in `POST /projects` and `GET /people/{handle}` also take; each project of the organisation emits `project_updated` and a ticker item (§6.24, §6.26).
