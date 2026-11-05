### Changed

- cli: `maity wait` retries an HTTP 429 like a 5xx, with the same cursor and
  never sooner than its `Retry-After`, until its timeout; it used to end with
  exit 1.
