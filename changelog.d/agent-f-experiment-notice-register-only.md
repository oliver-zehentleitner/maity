### Changed

- web: the "early public experiment" notice is shown only on the registration's
  completion page. The join panel and the runner's start no longer show it or its
  **Understood** button, and `M.experimentNotice` and the dashboard's
  `experiment.*` catalog keys are gone. `GET /me` still carries
  `member.experiment_notice_understood_at`, and `PATCH /me`
  `{"experiment_notice_understood": true}` still sets it, but no page of the
  dashboard asks for it.
