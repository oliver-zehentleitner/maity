### Added

- hub: abuse reports (§16.8), first part. `POST /reports` reports a profile, a
  project, a message or a card the caller can read (`not_found` otherwise, as a
  read answers), with a copy of the target as they read it; at most 20 per account
  a day and 3 per target. The instance admin gets a `report_open` inbox item, mailed
  by the `inbox` mode, and reads reports in `GET /admin/reports` and
  `GET /admin/reports/{id}`; `POST /admin/reports/{id}/resolve` takes `dismiss` for
  now (`hide`, `remove` and `suspend` follow). `GET /me/reports` shows the caller's
  reports, status and action only, and the account export carries them. An open
  report expires after 90 days, and a closed one's content goes 90 days later.
