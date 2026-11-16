### Added

- hub: every answer under `/api/v1/` carries `Maity-Web-Version`, the version of the
  dashboard it serves, and the app shell carries the same value (docs/api.md §1.1, §16.11).
- web: after a new version of the dashboard is deployed, an open page shows a band above
  the header with Reload and Later; it never reloads by itself, and with text typed the
  browser asks before the reload.
