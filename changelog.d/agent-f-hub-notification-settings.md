### Added

- hub: `GET` and `PATCH /me/notification-settings` (`docs/api.md` §18.4)
  — browser and mail preferences per kind, language, time zone, daily
  time, quiet hours, the sign-in link switch; an address verified by a
  24-hour link (the newest one only), a verified one changed only with the
  password or, for a human without one, approved from a session at least
  24 hours old (held changes, approve and reject); the old address told
  once and `email_address_changed` recorded. `POST …/email/verify`.
  Migration `0036`.
- hub: `/mail/verify/{token}` and `/mail/unsubscribe/{token}` (§18.6),
  signed with `MAITY_MAIL_SIGNING_KEY`, English or German, a `GET` never
  changing anything, the RFC 8058 one-click `POST`, tokens masked in the
  request log.
- hub: the mail outbox and its worker — mail written in the deciding
  transaction, sent in the background, counted per budget kind; security
  mail over its budget waits, sign-in mail over its budget is dropped,
  `enabled: false` holds everything, failures of the instance's setting
  retried for 24 hours; three hard failures in a row disable the address
  and write `mail_disabled` (§18.7); rows leave the outbox after a week.
- hub: the registration mail budget (§16.2): `registration_max_per_hour`
  (default 30, `MAITY_MAIL_REGISTRATION_MAX_PER_HOUR`), dropped over it
  like sign-in mail, `registration_sent_last_hour` and
  `registration_dropped_last_hour` in the mail settings.

### Security

- hub: a wrong `current_password` on an address change is refused with
  `rate_limited` once the login limits are spent, like the login itself.
- hub: notification items carry `content` (chat, mention) when the
  human's `browser.content` asks for it (§18.2).
