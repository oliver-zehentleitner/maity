### Added

- hub: `GET /projects/{slug}/messages` (§8.8): the project's messages, chats excluded, newest
  first, with the `type`, `before`, `after`, `limit` and `cursor` parameters. It lists what
  `GET /events` lets the caller read, and a redacted message stays as a tombstone.
  A page examines a bounded number of events; a sparse filter continues on the next page
  through `next_cursor`, which may then come with fewer items than `limit`.
