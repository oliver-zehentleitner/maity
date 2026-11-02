### Changed

- Hub: with several replicas on PostgreSQL, a removed forge token and the reads of a project's
  former repository go from every process's caches at once, not only from the one that took the
  request.
