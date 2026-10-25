### Added

- hub: two-factor sign-in for humans (`docs/api.md` §2.8) — a TOTP app
  (RFC 6238, own implementation, no new dependency) and ten recovery
  codes, the secret sealed and the codes kept as HMACs under
  `MAITY_SECRET_KEY`; enrolment behind the password given within ten
  minutes (`POST /auth/reauthenticate`) or, without a password, a session
  in good standing at least a day old; `GET`, `DELETE
  /auth/second-factor`, `POST …/totp`, `…/totp/confirm`,
  `…/recovery-codes`, `…/verify`. Migration `0046`.
- hub: the second step of a sign-in — after the password or a device
  code an enrolled human's session reaches only `GET /auth/session`, the
  verify and logout for five minutes; the verify re-keys the session and
  only then counts the sign-in; five wrong codes end it and alert the
  human; every code is accepted once.
- hub: step-up — address changes and approvals, the password change,
  the factor's own changes, joins, runner enrollments, device-code
  approvals and the instance settings need the factor within ten
  minutes.
- hub: the instance policy `second_factor` (`off`, `optional`,
  `required_admins`; `MAITY_SIGN_IN_SECOND_FACTOR`) in
  `/admin/settings/sign-in`; `required_admins` holds admins and owners at
  an enrolment session and needs the instance key (the hub does not start
  without it, the `PATCH` is refused); `off` ends open second steps and
  tells every enrolled human.
- hub: the account records `second_factor_changed` and
  `second_factor_failed` as `security` notifications and security mail.
