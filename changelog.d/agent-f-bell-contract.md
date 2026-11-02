### Changed

- docs/api.md §2.6.5, §18.3: reading a security alert no longer confirms a sign-in. "This was me" is a call
  of its own (`POST /auth/sessions/{id}/confirm`), good standing follows from it, and the mail sign-in banner
  stays until the session is confirmed. `up_to` with `include_security: true` marks security alerts read
  too, and the answer names what it left in `skipped`.
- docs/api.md §2.6.5, §2.8.5: a session confirmed by a read mark before the hub change keeps its good standing,
  with `confirmed_at` and `confirmed_by` taken from that read mark; the confirm runs in one transaction with its
  checks; a session moved into the enrolment state reaches the confirm as well as the bell.

### Added

- docs/api.md §18.2: `pinned`, every unread security alert at any age, for a block at the top of the bell;
  §18.8: the bell's "unread only" filter and the confirm before "mark all read" includes security alerts.
