### Changed

- hub: an attachment upload runs the authentication checks that need no body
  before it reads the body; a call that fails one gets that refusal with its
  body unread (docs/api.md §8.7).
- hub: a request body has to arrive within 120 seconds of the hub starting to
  read it, else the call is `408 request_timeout` and the connection closes
  (docs/api.md §1.3, §1.7).
- hub: the body is read into one growing buffer instead of a new copy per
  chunk.

### Added

- web: words for `request_timeout`.
