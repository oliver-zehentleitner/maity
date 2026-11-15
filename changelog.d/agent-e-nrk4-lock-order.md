### Fixed

- hub: confirming an account deletion no longer deadlocks with a password reset link, the link
  that lifts the daily second-factor cap or an admin's second-factor reset link of the same
  human pressed at the same moment. Each link now takes the account's lock first, as the
  deletion does, so one waits for the other (§2.8.3, §2.8.6, §2.9, §2.10).
