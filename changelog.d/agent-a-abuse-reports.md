### Added

- docs/api.md §16.8: abuse reports on profiles, projects, messages and cards (`POST /reports`,
  `GET /me/reports`), handled by the instance admins (`GET /admin/reports`, `…/resolve` with
  `dismiss`, `hide`, `remove`, `suspend`); a report keeps a snapshot of what was reported, the one
  content an instance admin reads; the reporter is never named to the reported member.
