### Changed

- contract: `placements` is a project view of §16.11, the dashboard's tab "Where they run" (where the project's agents run,
  §15.5–§15.7), so `/<owner>/<slug>/placements` is that view. Contract only, besides `placements` in the hub's list of project
  views (already reserved as a slug, being an API route word, §6.25); the dashboard follows in PR 2.
- contract: the global agents page gets two tabs of its own, `/agents/placements` ("Where they run") and `/agents/maintenance`
  ("Maintenance notices", until now at the bottom of `/agents`); the hub never issues either word as an id.
