### Changed

- web: the Messages view pages through the hub's message listing
  (`GET …/messages`, docs/api.md §8.8): its newest 50 first, older pages
  behind **Older messages**, the type filter the hub's. A message more than
  5000 events behind the hub's head is no longer cut off. New messages still
  arrive live, read with `after=` when the feed signals one and following
  the listing's cursor past pages its scan budget left short or empty, also
  under a type filter; a removed message stays as its tombstone in the
  unfiltered list. An empty page with more behind it says older messages
  are unread rather than that there are none, and **Older messages** keeps
  the keyboard focus.
- web: a member's Activity keeps its window of the hub's latest 5000 events,
  now its own scan; the fixture hub serves the message listing.
