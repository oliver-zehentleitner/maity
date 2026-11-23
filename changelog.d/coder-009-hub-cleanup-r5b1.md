### Fixed

- hub: a project's full name with a trailing newline (`<owner>/<slug>\n`) names no project
  anywhere: `namespace.resolve`, a profile's `allowed_projects` and `GET /agents?allowed_in=`
  refuse it as every other malformed name.

### Changed

- hub: clean-up from audit round 5, batch 1 (no change to any answer): one leaf module
  `chunks` bounds every IN list over many ids (export, public lists, reports, load test
  purge, and `namespace.full_names` itself); the cards naming a pull request are found by
  `cards.naming_pr`; one `views.handles_of` for principal handles; the export builds its
  abuse reports in one batch; `Forge.forget_visibility` is public for the Keep the Why reads;
  the not-listening digest reads only open episodes of its holders' projects; two more callers
  take their project locks through `events.lock_projects`.
