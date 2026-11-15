### Security

- hub: changing the password in the account (`POST /auth/password`) writes the account record
  `password_changed` `{ip, browser, os}`, a `security` notification whose mail goes out at once,
  as a password reset's does (§2.1, §18.1).
- hub: a daily cap of wrong second-factor codes per human, `MAITY_SECOND_FACTOR_WRONG_PER_DAY`
  (default 50): at it every TOTP or recovery-code check of that human is `rate_limited`
  (`details.reason: daily_limit`) until the UTC day ends, and `second_factor_failed`
  (`method: daily_limit`) is written; its mail carries a single-use link,
  `/mail/second-factor-unlock/{token}`, that starts the day's count again and dies with a
  password change. Nobody is refused before that alert is written, also after the cap was
  lowered during the day (§2.8.6, §18.6).
- hub: revoking a join link records `revoked_by` in the join's view and writes the humans-only
  event `join_revoked` `{id, agent_id, trust, role, revoked_by}`: by `DELETE`, by deleting the
  agent profile it names, and at the end of its creator's membership. The hub's own
  revocations (a runner's pickups, an account's deletion) leave `revoked_by` null and write
  no event (§3.1, §8.2).
