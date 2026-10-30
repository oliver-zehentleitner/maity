### Changed

- docs/api.md §7, §8.2: an instance address in a request's `to` wakes that one instance only and
  is resolved as in a message (a replaced instance's address reaches its successor, a revoked one
  is accepted and wakes nobody); `request_created` then goes to `instance:`, and
  `request_answered`/`request_withdrawn` go to the asking instance rather than its whole team,
  `member:` remaining for a human asker and a request the hub filed.
