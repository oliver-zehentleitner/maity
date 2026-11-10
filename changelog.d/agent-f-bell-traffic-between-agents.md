### Changed

- docs/api.md §18.2: `GET /me/notifications` picks its candidate rows in SQL so that the messages
  and requests agents exchange among themselves are left out; the exact test still decides each
  candidate. Before, that traffic was read and classified chunk by chunk to the end of the 30-day
  window, so the call's cost grew with it, also for `limit=0`, the counts the dashboard reads on
  every page. `limit=0` now skips deriving the page's items; the counts and the pinned alerts are
  derived as before. The answer is the same.
