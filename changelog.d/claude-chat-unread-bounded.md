### Changed

- hub: the group-chat unread nudge (`chat_unread`, §9.2) bounds the database work of each
  pass by its budget instead of the unread history: the one-row aggregates over a stay's
  unread range are gone, redactions are found through the project's `event_redacted` events,
  and the newest message is an index read. Who gets a nudge, when, and its payload are
  unchanged.

### Fixed

- hub: the unread nudge now comes at any rate of new messages: a read's bound grows only once
  the read has reached it, so a chat with 2000 or more new human messages between passes no
  longer keeps the nudge from ever coming.
