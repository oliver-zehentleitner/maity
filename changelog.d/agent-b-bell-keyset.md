### Fixed

- hub: `GET /me/notifications` reads every source (events, chat messages, account records)
  only as far as its page reaches and counts with its own few items, so a page no longer
  grows with the number of unread inbox items; the events of personal requests are left out
  in SQL and the open personal requests are counted in SQL (§18.2 unchanged)
