### Added

- Contract: a forgotten password is reset by mail (§2.10). `POST /auth/password-reset` always answers `202`, and the link stays valid for 30 minutes with its token in the fragment. With TOTP enrolled, the reset also needs a TOTP or recovery code. It ends every session and leaves agent credentials alone. A per-human switch `email.password_reset` and an instance switch `password_reset` turn it off, and `GET /auth/methods` gains `password_reset`. Humans whose second factor is the mail get a banner pushing toward an authenticator app. The routes are not served yet.
