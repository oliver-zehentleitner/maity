### Added

- Web: a released project (`released_at`, §6.1) shows a "Released" mark beside its state: in the
  header, with the released rules in its tooltip, on the overview, and in Project settings with
  the date and that the mark is never cleared. The overview also shows the state.
- CLI: `maity resume` prints `, released` after the project's state when the packet carries
  `released_at`.

### Changed

- CLI: the empty board of a closed project and the `claim --reason` help use the states of
  §6.1 (`archived`; `plan` and `review`) instead of `accepted`, `freeze` and `fixes-only`.
