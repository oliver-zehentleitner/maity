### Changed

- cli: `maity wait` waits at least a 503's `Retry-After` before it reads again, as it did for a 429; the hub sends one with `database_unavailable` (an unreachable or busy database). Other 5xx keep the plain back-off, and the wait's deadline still caps every pause.
