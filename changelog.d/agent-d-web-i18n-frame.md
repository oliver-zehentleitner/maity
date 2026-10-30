### Changed

- Dashboard: the frame's words come from the catalog: the header (where one is, the fixtures tag, the
  state group, away), the tabs and their reload notices, the project states, the gear and profile
  menus, and `dom.js` (relative times, the name rules, an ambiguous mention, an instance's title, an
  agent's silence); dates in `formatTime` through `M.fmt`. The ambiguous-mention message is one
  sentence with the long forms joined by `Intl.ListFormat`. The baseline is lowered for `app.js`
  and `dom.js`.
- Web e2e: the join-expiry step's route handler is quiet only about a closed tab; other errors are
  problems of the run.
