### Changed

- hub: the group-chat unread nudge (`chat_unread`, §9.2) bounds the database work of each
  pass by its budget instead of the unread history. The one-row aggregates over a stay's
  unread range are gone. The read's limit counts every event row of the chat, so agents' or
  redacted messages cost no more than human ones. Redactions are found through the project's
  `event_redacted` events. The newest message is an index read. Who gets a nudge, when, and
  its payload are unchanged.
- hub: the open read cycle of the unread nudge is stored per stay
  (`conversation_participant.unread_nudged_through`, migration
  `20261109140000_nudged_through`, filled from the nudges already written), written with the
  nudge under the project lock. A second worker process can no longer write a second nudge
  for the same messages, and the check reads no event log.

### Fixed

- hub: the unread nudge now comes at any rate of new messages, redactions or events about the
  chat. A read's bound grows only once the read has reached it, and the redaction look has a
  bound of its own. So 2000 or more new human messages between passes, a stream of later
  redactions or title changes, or other chats' nudges no longer keep the nudge from ever
  coming.
