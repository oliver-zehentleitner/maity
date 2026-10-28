### Added

- Dashboard: Project settings shows the project's full name and its earlier names to a human owner. It renames the slug (`PATCH /projects/{owner}/{slug}` `{slug}`), and the namespace owner can transfer the project to another human owner (`POST …/transfer`). The transfer is a consent request the receiver accepts in their inbox, and it can be withdrawn. The hub's `taken`, `reserved`, `alias_limit`, `rate_limited` and a required step-up are said in words (docs/api.md §6.25).
- Dashboard: outside its project, a card's or request's id reads `<owner>/<slug>/tsk-…`, in the global chat and across projects (tsk-cns4d1d7ht4j).

### Changed

- Dashboard: Members says `namespace_owner` when someone tries to demote or remove the project's namespace owner, and points to the transfer. The ticker names a `rename` item.
