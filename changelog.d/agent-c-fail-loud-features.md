### Changed

- cli: a 404 on a route the hub's `openapi.json` does not list now says "this
  hub does not have <feature> yet" and names the route, instead of a
  `not_found` that reads like a mistyped id; an unreadable document keeps the
  original error. `maity chat cnv-…` says when the hub has no group chats, and
  the runner's pickup logs a missing `POST /runner/placements/{id}/join` and
  fails with `join_failed`/`not_found`.

### Fixed

- cli: `maity link list` refuses a card without a `links` list instead of
  printing "no links".
