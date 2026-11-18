### Added

- Contract: the history of a human's own agent-firewall decisions (§9.6,
  `GET /me/chat-access/history`, not built). Each change of an allow or
  deny entry (created, changed, deleted, expired) with when, how (the
  Chat access lists, an answer to a request, the owner's add to a chat,
  the end of `until`, a deletion of what it named) and the entry as it
  was, and each answer to the request to chat with the owner's agents
  with its button, the ticked agents, whether the person was ticked and
  the entries it wrote. Only the owner reads it, newest first, paged;
  kept as long as the account, at most the newest 10,000 items, deleted
  with the account and in the export (`chat_access_history`). It starts
  with the version that brings it.
