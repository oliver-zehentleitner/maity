### Changed

- contract: `placements` is a project view of §16.11, the dashboard's tab "Where they run" (where the project's agents run,
  §15.6), so `/<owner>/<slug>/placements` is that view and no project slug may be `placements`. Where the database already
  holds such a slug or project alias, this release's `maity-hub migrate` refuses and names it until it is renamed, as for every
  reserved word; a hub started past that logs the holders and runs.
- contract: the global agents page gets two tabs of its own, `/agents/placements` ("Where they run") and `/agents/maintenance`
  ("Maintenance notices", until now at the bottom of `/agents`); the hub never issues either word as an id.
