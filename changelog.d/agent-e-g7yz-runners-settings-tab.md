### Changed

- web: a project's runners are the **Runners** tab of its Settings, at
  `/<owner>/<slug>/settings/runners`, for the project's admins as before:
  the attached runners, **Allow it here** and **Detach**, with the same
  refresh. The link from General is gone, and the start on a runner's
  "Allow one under …" leads to the tab. English and German.

### Removed

- web, hub: the project view `/<owner>/<slug>/runners`, without a
  redirect: the dashboard says "not found" and the hub answers `404` with
  the app shell (§16.11). `runners` stays reserved as a slug.
