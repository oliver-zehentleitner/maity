### Added

- hub: a change of the second factor (`second_factor_changed`: enrolled, disabled, new recovery
  codes, a recovery code used, a reset, the instance switching it off) and wrong second-factor
  codes after a sign-in (`second_factor_failed`) are now `security` items of the bell with the
  titles of `docs/api.md` §18.1, and each is mailed on its own as a security mail while the
  human's `security` mode is `immediate`, never batched and not held by quiet hours (§2.8.1,
  §18.5).
