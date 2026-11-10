### Added

- Hub: the resume packet's `project` carries `released_at` (§5, §6.1), `null` until the probe sets
  the mark, so `maity resume` can show `, released` beside the state.

### Changed

- docs/api.md §8.2: a `state_changed` from the released mark has `old == new`, `reason: null` and
  adds `released_at`.
