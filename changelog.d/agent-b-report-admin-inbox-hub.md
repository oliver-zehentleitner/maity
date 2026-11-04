### Changed

- Hub (§16.8, §7): a new abuse report files a personal request to the instance admin, with no
  project, carrying `report: {id, reason, type}` and no replies; its title is in the admin's
  language. Answering or withdrawing it is `resolve_the_report` (409). Resolving the report or its
  expiry withdraws the request. The account record `report_open` is no longer written or shown. A
  migration adds `request.report_id` and files a request for every report still open.
