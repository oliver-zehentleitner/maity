### Added

- hub: `GET` and `PATCH /me/notification-settings` (`docs/api.md` §18.4) — what the
  browser shows and what is mailed how often per kind (`inbox`, `chat`, `mention`,
  `security`), the daily time, quiet hours, time zone, language and the sign-in link
  switch. Only what the human changed is stored; the defaults fill the rest, and a
  human who never changed anything has no row. Settings stored for the kinds removed on
  2026-10-26 govern nothing and go with the next `PATCH`; naming one is `removed_kind`.
  The address (setting, verifying, changing) is not served yet: `email.address` is
  `invalid`, `not_available`. Migration `0064`: `notification_settings` and
  `address_lock`.
