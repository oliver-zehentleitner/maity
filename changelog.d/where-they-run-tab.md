### Changed

- contract: `placements` is a project view of §16.11, the dashboard's tab "Where they run" (where the project's agents run,
  §15.6), so `/<owner>/<slug>/placements` is that view and no project slug may be `placements`. A hub whose database already
  holds such a slug or project alias refuses to start until it is renamed, as for every reserved word.
