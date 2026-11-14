### Added

- hub: an "early public experiment" notice. The registration's completion page
  shows it above the button; it is shown nowhere else. `GET /me` carries
  `member.experiment_notice_understood_at`, `PATCH /me`
  `{"experiment_notice_understood": true}` sets it, and the export holds it.
