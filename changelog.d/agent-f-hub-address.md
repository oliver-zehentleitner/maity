### Added

- hub: the notification address (`docs/api.md` §18.4, §18.6, §18.7) — `PATCH
  /me/notification-settings` sets `email.address`, which waits as `pending_address` and
  is mailed a confirmation link valid for 24 hours; the verified address keeps receiving
  until the new one is confirmed. `/mail/verify/{token}` (`GET` shows, `POST` confirms) and
  `POST /me/notification-settings/email/verify` confirm it. Changing or removing a verified
  address needs the password, or for a human without one a session in good standing that is
  at least a day old (held as `address_change`, approved or rejected at
  `…/address-change/approve` and `…/reject`); the old address hears of it once. One account
  per verified address, under a per-address lock. Three permanent failures disable the
  address and ask the human in the inbox. A registration's completion now claims its
  address through the same store: registration, which could not complete before, does.
