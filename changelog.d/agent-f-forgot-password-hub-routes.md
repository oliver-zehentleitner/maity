### Added

- hub: a forgotten password is reset by mail (docs/api.md §2.10). `POST /auth/password-reset`
  always answers `202` and mails a 30-minute link `/sign-in/reset#<token>` to a verified
  address of an active account with a password whose human has not switched it off, from the
  reset mails' own budget. `POST /auth/password-reset/check` names the account and what the
  reset asks for (`factor`); `POST /auth/password-reset/complete` sets the password, with a
  TOTP or recovery code for an enrolled human, ends every session (`ended_by:
  password_reset`), every sign-in and reset link, an unconfirmed new address and a pending
  account deletion, signs nobody in, and writes the account record `password_reset`, a
  `security` notification mailed at once. A dead link and a wrong code are both
  `code_invalid`; the fifth wrong code at resets of a human in 24 hours, and every further
  one, voids every open reset link and writes `second_factor_failed` (`method:
  password_reset`), titled "Wrong second-factor codes at a password reset" in the bell and
  the mail. A maintenance window refuses the three calls.

### Changed

- hub: `password_reset_missing` no longer names `not_implemented`: with mail ready the reset is
  offered, and `password_reset` in `GET /auth/methods` is `true`.
