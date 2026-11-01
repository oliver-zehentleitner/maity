### Fixed

- hub: `GET /auth/second-factor` carries `via` (`totp`, `email` or `null`), as docs/api.md §2.8.8 says. The limit of three mails per second-factor session is taken in the update itself, so two sends at once cannot both take the third.
