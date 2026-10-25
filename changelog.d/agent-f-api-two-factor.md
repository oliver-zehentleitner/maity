### Added

- docs/api.md §2.8: two-factor sign-in for humans — a TOTP app and ten
  recovery codes for every account, sealed with `MAITY_SECRET_KEY`,
  enrolled with the password re-given (`POST /auth/reauthenticate`) or,
  without a password, from a session in good standing at least 24 hours
  old, or from any session when the human has no session in good
  standing at all; recovery codes and reset links bound to the factor's generation;
  a lost instance key fails closed;
  a second-factor session after every first factor (password, device
  code, mail link) that reaches nothing but the verify and logout; step-up
  within 10 minutes before sensitive calls; the instance setting
  `second_factor` (`off`, `optional`, `required_admins`,
  `MAITY_SIGN_IN_SECOND_FACTOR`); the instance admin's reset confirmed by
  the human by mail, and the operator's `maity-hub second-factor reset`;
  the account records `second_factor_changed` and `second_factor_failed`;
  rate limits; the dashboard's part. The defaults as the maintainer
  settled them. Cross-references in §1.3, §2.1,
  §2.6.5, §2.6.6, §12, §16, §18.1 and §18.6.
