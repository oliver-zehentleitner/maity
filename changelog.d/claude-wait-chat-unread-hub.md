### Added

- hub: the group-chat unread nudge (docs/api.md §9.2). The not-listening worker's minute pass sends an
  agent participant one `chat_unread` per chat and read cycle. It counts human messages after its read
  mark that did not mention it, once the oldest is 10 minutes old, and only while one of its instances
  listens. It is readable only by that agent. The generated rules tell agents to read the chat it names.
