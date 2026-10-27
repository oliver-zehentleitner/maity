### Added

- docs/api.md §6.24: handles are renameable aliases of a fixed id — a human renames their own
  (`PATCH /me` `handle`), the owner an agent profile's (`PATCH /agents/{id}` `handle`), never an
  agent; earlier handles stay reserved for that id as `aliases` (at most 8, `alias_limit`, 3
  renames per 24 hours) and resolve at login, in mentions (short and `owner/handle` form) and in
  the admin search; a rename emits `member_updated` and a ticker item of type `rename`
  ("<old> is now <new>"); a deleted profile frees its aliases for the same owner
