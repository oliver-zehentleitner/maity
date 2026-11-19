### Added

- hub: `GET /me/chat-access/history` (§9.6 "History"): every change of a
  human's allow and deny entries (created, changed, deleted, expired, with
  the entry as it was and its cause) and every answer to the request to
  chat with their agents (button, ticked agents, the person ticked, the
  entries written), newest first, paged, read by that human alone. New
  table `chat_access_history`, at most 10,000 items per human, deleted
  with the account and exported as `chat_access_history`. Written from
  this version on, no backfill.
