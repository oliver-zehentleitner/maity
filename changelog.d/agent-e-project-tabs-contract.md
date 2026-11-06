### Added

- docs: `GET /me` names each project by its fixed `id` and carries the
  human's `start_tabs`, the projects a browser with no tabs of its own
  opens, in order. `PATCH /me` sets that list, and every later
  membership joins it at the end. The open tabs, their order and the
  inbox's filter to open tabs stay in the browser.
