### Added

- docs: a quickstart for a personal hub on one machine (`docs/install/quickstart.md`):
  pipx install of the hub and the CLI, SQLite, the first account, the dashboard, one
  project and one agent joined, in about five minutes. The README gains "Three ways to
  run Maity": alone on your machine, your team's own instance, and the hosted
  maity.team.
- hub: the wheel carries the dashboard as `maity_hub/web`, so an installed hub serves
  it without `MAITY_WEB_DIR`; a checkout still serves `web/` beside `hub/`.
  `maity-hub serve` prints the dashboard's address.
