### Fixed
- cli: `maity wait` retries HTTP 5xx responses and dropped connections with
  bounded exponential backoff until its timeout, retaining the event cursor.
  An outage now ends with timeout exit 3 instead of error exit 1; HTTP 4xx
  responses remain errors.
