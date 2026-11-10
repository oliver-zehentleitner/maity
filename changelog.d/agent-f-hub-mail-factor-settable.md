### Added

- hub: `second_factor: email` can be set (§2.8.8). `PATCH /admin/settings/sign-in` answers `202` and mails the admin a code, `POST /admin/settings/sign-in/second-factor-email/confirm` turns it on; `mail_not_ready` and `no_verified_address` refuse it. `MAITY_SIGN_IN_SECOND_FACTOR=email` takes effect at once, and the hub refuses to start with it without complete mail settings.
- hub: `address_hint` in `GET /auth/session` during the second step under `via: email`, masked (§2.8.7).

### Changed

- hub: under `email` the sign-in link is off: `email_link: false`, `second_factor_email` in `missing`, and `POST /auth/email-link` answers `202` and sends nothing.
- hub: removing the verified address under `email` is refused for a human without TOTP (`second_factor_required`).
- hub: the downgrade of the `mail_factor` migration refuses while `sign_in.second_factor` is stored as `email`.

### Fixed

- hub: a mail factor send that loses the race for the session's third mail no longer spends one of the human's ten an hour.
