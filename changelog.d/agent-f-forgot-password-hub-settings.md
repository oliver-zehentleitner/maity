### Added

- hub: the settings of the password reset by mail (docs/api.md §2.10), ahead of its routes.
  `password_reset` in `GET, PATCH /admin/settings/sign-in` with `MAITY_SIGN_IN_PASSWORD_RESET`,
  `password_reset_available` and `password_reset_missing`; `password_reset` in
  `GET /auth/methods`; `email.password_reset` in the notification settings; the reset mails'
  own budget `password_reset_max_per_hour` (`MAITY_MAIL_PASSWORD_RESET_MAX_PER_HOUR`, default
  30) with its counters. Until the routes come, `password_reset_missing` names
  `not_implemented` and the reset is never offered.
- hub: migration `20261112110000_password_reset`: `human.password_generation`, and the tables
  `password_reset` and `password_reset_wrong`, deleted with the account.

### Fixed

- hub: `POST /auth/password` voids an unconfirmed new address and its verification link, as
  docs/api.md §2.10 says it does, and moves the password generation.
