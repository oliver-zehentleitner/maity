### Added

- hub: `GET` and `PATCH /me/notification-settings` (`docs/api.md` §18.4)
  — browser and mail preferences per kind, language, time zone, daily
  time, quiet hours, the sign-in link switch; an address verified by a
  24-hour link (the newest one only), a verified one changed only with the
  password or, for a human without one, approved from a session at least
  24 hours old (held changes, approve and reject); the old address told
  once and `email_address_changed` recorded. `POST …/email/verify`.
  Migration `0035`.
- hub: `/mail/verify/{token}` and `/mail/unsubscribe/{token}` (§18.6),
  signed with `MAITY_MAIL_SIGNING_KEY`, English or German, a `GET` never
  changing anything, the RFC 8058 one-click `POST`, tokens masked in the
  request log.
- hub: the mail outbox and its worker — mail written in the deciding
  transaction, sent in the background, counted per budget kind; security
  mail over its budget waits, `enabled: false` holds everything, failures
  of the instance's setting retried for 24 hours.
- hub: notification items carry `content` (chat, mention) when the
  human's `browser.content` asks for it (§18.2).
