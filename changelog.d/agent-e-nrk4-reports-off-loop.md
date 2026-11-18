### Fixed

- hub: several requests no longer block the server's event loop with a database transaction:
  filing an abuse report, an admin's resolving one, completing an email sign-in link, and
  reading a device code's status (`GET /device-codes/{id}`, `GET /device-login`). On SQLite such
  a request could wait out the 5 s busy timeout behind another request's sign-in check and
  answer 503 `database_unavailable` (tsk-pzex5cpkv6tx). The same holds for the rate limits that
  are shared on PostgreSQL: the sign-in, registration, invitation, join, runner pairing and
  forge webhook limits now count off the loop as well. A test now fails for any `async` route
  that runs a sync transaction on the event loop, also through a helper or a limiter.
