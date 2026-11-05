### Changed

- web: the bell no longer shows sign-ins: its pinned block holds the other security alerts, each
  with Mark read. The Notifications page gains a small "Current sessions" box with the active
  sessions and a link to Profile → Sessions; it is read again when the hub's `sessions_rev`
  moves, and the mail sign-in banner follows the same change. The bell counts them as "Security
  alerts" (no longer "Sign-ins and address"), and on a phone a pinned alert's link keeps its
  distance from Mark read.
