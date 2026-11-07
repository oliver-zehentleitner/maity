### Added

- hub: `GET /me` names each project by its fixed `id` and carries a
  human's `start_tabs`. `PATCH /me` sets that list (current memberships,
  each once), every new membership joins its end, the export holds it with
  full names, and an account deletion clears it.
- web: the project tabs are this browser's own. A tab moves by dragging,
  by Alt+Shift+Arrow or from the new tabs menu, which also opens and
  closes projects and keeps the row as the start set; a project's Mine
  settings switch it in or out of that set, and the cross-project inbox
  can be filtered to projects with an open tab.
