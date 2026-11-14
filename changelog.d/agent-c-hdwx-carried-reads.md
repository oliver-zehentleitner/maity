### Security

- hub: carried reads apply the bridge's own isolation windows. A bridge reading for an agent
  (`Maity-For`, `?for=`) is held to the hidden isolation windows of its own membership as well
  as the agent's, on every read that hides a window: events, project messages, conversations,
  a card's history. Card notes, the card search over notes and a restricted text's history
  entries now also leave out what lies in the reader's hidden windows. A bridge no longer reads
  or wakes on `cross_chat_mention` for the agent it serves, as for `chat_rules_changed`.
