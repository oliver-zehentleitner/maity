### Added

- docs/api.md §2.8: two-factor sign-in for humans — a TOTP app and ten
  recovery codes, sealed with `MAITY_SECRET_KEY` (an account without a
  password enrols behind the 24-hour guard of §2.6.3);
  a second-factor session after every first factor (password, device
  code, mail link) that reaches nothing but the verify and logout; step-up
  within 10 minutes before sensitive calls; the instance setting
  `second_factor` (`off`, `optional`, `required_admins`,
  `MAITY_SIGN_IN_SECOND_FACTOR`); the instance admin's reset confirmed by
  the human by mail, and the operator's `maity-hub second-factor reset`;
  the account records `second_factor_changed` and `second_factor_failed`;
  rate limits; the dashboard's part. Defaults not yet settled by the
  maintainer are marked as proposals. Cross-references in §1.3, §2.1,
  §2.6.5, §2.6.6, §12, §16, §18.1 and §18.6.
