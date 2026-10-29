### Added

- web: New project offers the owner, the human or an organisation that lets them create projects,
  where the hub takes `owner` (docs/api.md §6.26); its refusals in words.
- web: Transfer moves a project into an organisation the human owns at once, or asks the owners
  of one they administer; any owner of an organisation transfers its projects.
- web: Your data names the organisations whose last owner the human is (`org_last_owner`).

### Changed

- web: the transfer asks for the password or a code in place where the hub wants the step-up,
  instead of saying to sign in again.

### Fixed

- web: a personal request without a project (an organisation's invitation, a transfer into an
  organisation) no longer breaks the inbox; it reads as Personal and names the organisation where
  the request carries it.
