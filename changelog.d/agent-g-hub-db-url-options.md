### Fixed

- hub: an `options` parameter in `DATABASE_URL` (such as `-c
  search_path=…`) is kept on PostgreSQL connections, before the hub's own
  `-c TimeZone=UTC` and timeouts, instead of being replaced by them.
