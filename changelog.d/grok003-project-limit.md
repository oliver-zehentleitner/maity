### Added

- hub: at most `max_projects_per_owner` projects in one namespace, a human's or an organisation's
  (`MAITY_MAX_PROJECTS_PER_OWNER`, default 10, archived projects counted): `409 project_limit` on
  `POST /projects` and on a transfer into a full namespace, when filed and at the `go`;
  `GET`/`PATCH /admin/settings/limits` show it with `owners_at_project_limit`. Lowering it takes
  nothing away (tsk-6q1z2z9t334e).

### Changed

- hub: an archived project's jour-fixe deadlines and schedule and its availability sweep (limits and
  absences ending, reconcile, due actions) are skipped; unarchived, it is back in the next run.
  Archiving is no freeze: work open when it was archived (leases, takeovers), presence, the forge
  runs and housekeeping still reach it.
