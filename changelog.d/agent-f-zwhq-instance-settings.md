### Added

- hub, web: Admin → Instance shows how the hub is configured: the version, the database schema
  and every `MAITY_*` setting with its value and whether it comes from the environment or is the
  default, secrets only as set or not set (`GET /admin/instance`, docs/api.md §16.14). Nothing can
  be switched there; the page says how a setting changes. A test fails when the hub reads a new
  setting the overview leaves out.
- docs: hub/README.md (Configuration) describes the GitHub App's five settings,
  `MAITY_ON_RUNNER_REVOKE`, `MAITY_MAX_PROJECTS_PER_OWNER` and `MAITY_MAX_ALIASES`.
