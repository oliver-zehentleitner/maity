### Changed

- hub: on PostgreSQL every rate limit, the registration and device-code breakers, the wrong codes
  of a second-factor session and the count of dropped registrations are shared by every replica
  (one UNLOGGED table, `rate_count`): a limit of up to 20 attempts counts every attempt exactly,
  a larger one reads a sliding window from two fixed ones; SQLite and MariaDB keep them in the
  process (replicas design, card 2)
- docs/api.md §2.2: on PostgreSQL a nonce is remembered for at least 600 s, until a sweep deletes
  it (review of #794)
