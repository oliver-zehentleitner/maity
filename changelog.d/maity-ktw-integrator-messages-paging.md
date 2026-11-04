### Changed

- web: the Messages view pages through the hub's message listing
  (`GET …/messages`, docs/api.md §8.8): its newest 50 first, older pages
  behind **Older messages**, the type filter the hub's. A message more than
  5000 events behind the hub's head is no longer cut off. New messages still
  arrive live, read with `after=` when the feed signals one; a removed
  message stays as its tombstone in the unfiltered list.
- web: a member's Activity keeps its window of the hub's latest 5000 events,
  now its own scan; the fixture hub serves the message listing.
