### Changed

- hub: an attachment upload checks its query for a leaked credential, then
  runs the first authentication checks before it reads the body: that there
  is a credential or a session cookie; for a bearer credential the transport,
  the credential and its secret; for a session cookie the transport,
  `Sec-Fetch-Site` and that the session is alive; for a signed call the
  headers' shape, the time window and that the credential exists. A call that
  fails one gets that refusal with its body unread (docs/api.md §8.7).
- hub: a request body, the forge webhook's included, has to arrive within 120
  seconds of the hub starting to read it, else the call is
  `408 request_timeout` and the connection closes (docs/api.md §1.3, §1.7).
- hub: both readers of a body, the middleware's and the forge webhook's, read
  it into one growing buffer instead of a new copy per chunk.

### Added

- web: words for `request_timeout`.
