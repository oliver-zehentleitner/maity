### Changed

- cli: version 0.1.0a9 for PyPI, with `maity wait` waiting at least a 503's `Retry-After` (the hub's
  `database_unavailable`) before it reads again, as it does for a 429.
