### Fixed

- docs/api.md §15.13: local mode's `maity wait` long-polls between runs keep the session online
  and renew no claim lease, as §2.4 and §8.3 already say; the sentence said they renewed them. A
  `claim_lease_expiring` (not built yet) wakes that wait, and the run it starts renews with
  `maity claim renew` or releases the card.
- cli: `maity claim --help` says that the events long-poll inside `maity wait` renews no lease,
  while the unread-chats check `maity wait` makes on a timeout is an ordinary call and does; and
  that an expired lease releases nothing: the card stays the holder's until it is given back or
  taken over.
