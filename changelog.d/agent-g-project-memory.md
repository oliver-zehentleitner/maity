### Added

- hub: a project's memory provider (`docs/api.md` §6.1, §6.21) —
  `memory: {provider}` on `POST`/`PATCH /projects` (`keep-the-why`, the
  default, or `none`), `keep_the_why` kept as its alias; a change bumps the
  rules with `rules_changed`.
- hub: the setup options chosen at creation (`setup`: Keep the Why init and
  badge, on by default; the Maity badge, off unless sent) and one `setup`
  card per option — titles verbatim, a pull request as the acceptance —
  created with the project, or when its repository is first set, never
  again; `setup` read back with the project and refused on `PATCH`.
- hub: the resume packet's `setup`, the setup cards that still wait.

### Changed

- hub: a project created without naming its memory uses Keep the Why; the
  `keep_the_why` column is replaced by `memory_provider` (migration 0049).
