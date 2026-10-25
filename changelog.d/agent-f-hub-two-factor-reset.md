### Added

- hub: the second factor's reset (`docs/api.md` §2.8.3) — `POST
  /admin/users/{id}/second-factor/reset` (`instance:admin`, step-up, never
  the admin's own) mails the human a link for 24 hours; it takes effect
  only on the button of `/mail/second-factor-reset/{token}`, in one
  transaction that ends every session of the human, and dies once the
  factor's generation moves (recovery, a new enrolment, turning off,
  another reset). `409 mail_not_configured` without mail, `409
  address_unverified` without a verified address, 3 requests per day per
  human. The next sign-in enrols first. `maity-hub second-factor reset
  --handle` resets at once on the server. The token is masked in the
  request log.
