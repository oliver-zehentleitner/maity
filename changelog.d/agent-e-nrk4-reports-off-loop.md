### Fixed

- hub: filing an abuse report, an admin's resolving one, completing an email sign-in link and
  reading a device code's status (`GET /device-codes/{id}`, `GET /device-login`) no longer
  block the server's event loop with their database transaction. On SQLite such a request
  could wait out the 5 s busy timeout behind another request's sign-in check and answer 503
  `database_unavailable` (tsk-pzex5cpkv6tx). A test now fails for any `async` route that runs a
  sync transaction on the event loop, also through a helper function.
