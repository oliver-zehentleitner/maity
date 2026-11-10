### Fixed

- hub: `GET /auth/methods` answers `registration` (true for `allowlist` or `open` with complete,
  enabled mail) and `terms` (`{url, version}` or `null`), as §2.6.1 and §2.7 say; without them the
  login page never offered "Create an account" and `/register` refused on every hub.

### Added

- web: the registration form names the instance's terms and their version, linked when the
  address is plain https.
