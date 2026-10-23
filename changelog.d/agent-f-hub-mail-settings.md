### Added

- hub: the instance's mail settings (`docs/api.md` §16.2) — `GET` and
  `PATCH /admin/settings/mail` for the instance admin, every value from
  `MAITY_SMTP_*` / `MAITY_MAIL_*` or set by the admin, the environment
  winning; the SMTP password write-only, stored only AES-256-GCM-encrypted
  with `MAITY_SECRET_KEY` and flagged in Kubernetes; `complete`, `missing`,
  `warnings` and the hourly counters. Migration `0020`.
- hub: the test send (`docs/api.md` §16.3) — `POST
  /admin/settings/mail/test`, one fixed mail to the configured server
  only, STARTTLS required (plaintext only with the insecure
  `MAITY_SMTP_ALLOW_PLAINTEXT`), `AUTH` only over TLS, certificates always
  verified (`MAITY_SMTP_CA_FILE`), the stage where it stopped and the
  server's reply without the username or password; five per hour.
- hub: `cryptography` as a dependency, for the encrypted SMTP password.

### Changed

- docs: §16.2 names the environment form of `MAITY_SMTP_FROM`
  (`Name <address>`) and the `PATCH` codes `extra_forbidden` and
  `loopback_host_only`.
