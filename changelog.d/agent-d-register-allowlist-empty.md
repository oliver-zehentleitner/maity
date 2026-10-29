### Changed

- hub: `GET /auth/methods` answers `registration: false` under `allowlist` while both lists are
  empty, so no way in is offered that nobody could finish (§2.7); the admin sees
  `missing: ["allowlist"]`.

### Added

- web: the context entry on the registration form's terms (48c34360), with the empty allowlist.
