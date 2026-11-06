### Changed

- Hub: reads under `/api/v1/` and the dashboard's files under `/assets/` of 1024 bytes and more are
  gzipped (level 6) when the client accepts it; writes, `/api/v1/auth/`, an attachment's bytes and
  the pages outside these prefixes are left as they are (docs/api.md §1.1).
