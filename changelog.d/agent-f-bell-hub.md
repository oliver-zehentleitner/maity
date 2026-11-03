### Added

- hub: `POST /auth/sessions/{id}/confirm`, "This was me" (§2.6.5). It confirms one of the
  caller's own sessions and marks its sign-in alert read; the session list shows `confirmed_at`
  and `confirmed_by`. A session moved into enrolment keeps this call while it is in good standing
  (§2.8.5).
- hub: `GET /me/notifications` answers `pinned`: every unread security item, newest first, at
  most 50, whatever the filters and the page; an answer to `after` carries none (§18.2).
- hub: `POST /me/notifications/read` takes `include_security: true` with `up_to` and answers
  `skipped`: the security items the calling session may not mark, each with `not_earlier` or
  `not_in_good_standing` (§18.3).

### Changed

- hub: reading a sign-in alert no longer confirms the session. Good standing follows from
  "This was me", a password or a second factor. Sessions whose alert was marked read before are
  carried over as confirmed, with the time of that read and the session that made it. Security
  kinds other than sign-ins and address changes may be marked read from any session of the
  human.
