### Added

- hub: `GET /me` names each project by its fixed `id` and carries a
  human's `start_tabs`. `PATCH /me` sets that list (current memberships,
  each once), every new membership joins its end, the export holds it with
  full names, and an account deletion clears it.
