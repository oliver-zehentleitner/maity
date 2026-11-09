### Changed

- hub: the group-chat unread nudge (`chat_unread`, §9.2) bounds the database work of each
  pass by its budget instead of the unread history. The one-row aggregates over a stay's
  unread range are gone. The read's limit counts every event row of the chat, so agents' or
  redacted messages cost no more than human ones. Redactions are found through the project's
  `event_redacted` events. The open-cycle check reads on from a cursor, so other agents'
  nudges are read once. The newest message is an index read. Who gets a nudge, when, and its
  payload are unchanged.

### Fixed

- hub: the unread nudge now comes at any rate of new messages, redactions or events about the
  chat (title changes, other agents' nudges). A read's bound
  grows only once the read has reached it, and the redaction look has a bound of its own. So
  2000 or more new human messages between passes, or a stream of later redactions, no longer
  keep the nudge from ever coming.
