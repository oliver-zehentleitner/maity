### Added

- hub: on PostgreSQL a newer long-poll of the same credential, dashboard session, runner or
  device code supersedes an older one on another replica too (`superseded: true`, §8.3): a wait
  announces itself on `maity_supersede` with the hash of its key and its start on the database
  clock, and only an older wait ends (hub/context/replicas.md 387c2409, point 3).

### Fixed

- hub: the wake-up listener's connection sets TCP keepalives, so a connection dropped silently
  is noticed after about a minute and opened again instead of leaving the replica deaf and the
  server's notice queue held (review of #869).
