### Changed

- hub: on PostgreSQL the nonces of signed requests live in the database (`request_nonce`, with
  `nonce_epoch`, both UNLOGGED), so a request spent on one replica is refused on every other;
  after a crash or a failover empties them, a request signed before is refused as
  `timestamp_skew`. SQLite and MariaDB keep the window in the process (replicas design, card 1)

### Fixed

- hub: `GET /people/{handle}` takes the hold rule for links from `person_links.admitted(held=…)`,
  the member views' own (review of #766)
- tests: a server database is emptied before the session's last downgrade, which an
  organisation's project left by the last test refused
