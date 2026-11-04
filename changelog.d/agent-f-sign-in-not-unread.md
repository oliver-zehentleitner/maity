### Changed

- docs/api.md §2.6.5, §18.1–§18.4, §18.8: a new sign-in (`session_created`) is no longer a
  notification. It is not listed, counted or pinned in the bell and has nothing to mark read,
  which ends alerts that only an older session could clear. The Notifications page gets a
  "Current sessions" box linking to Profile → Sessions. `GET /me/notifications` gains
  `sessions_rev`, and its long-poll also returns on a session record. The sign-in mail, the
  banner of a mail sign-in and "This was me" stay. `email_address_changed` keeps its read
  rule.
