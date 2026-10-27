### Changed

- cli: project routes are `/projects/<owner>/<slug>/…` (§6.25); the state keeps the project's
  `full_name`, refreshed by every `maity resume`, and a state from before the namespace reads
  it once from `GET /me`; `client_outdated` (426) prints the minimum version and the upgrade
  line; `maity resume` shows the full name and names `<owner>/<slug>` in its read-more hints
