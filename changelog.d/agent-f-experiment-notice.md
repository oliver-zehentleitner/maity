### Added

- hub, web: an "early public experiment" notice. The registration's completion
  page shows it above the button; the join panel and the runner's start show it
  with **Understood** until the person confirms it once. `GET /me` carries
  `member.experiment_notice_understood_at`, `PATCH /me`
  `{"experiment_notice_understood": true}` sets it, and the export holds it.
  `M.experimentNotice` is the reusable notice for other places.
