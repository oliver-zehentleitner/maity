### Added

- docs/api.md §6.11: the project overview — repository and Keep the Why dashboard links from
  the project as it is (no new settings; `repository` stays human-only `project:admin`), members
  and policy preset from the existing reads, and one new `GET /projects/{slug}/overview` with
  card counts per status, the caller's visible open requests and the latest reports (merges
  as observed by the probe); a contract note for the dashboard's `#/p/<slug>/overview` view.
