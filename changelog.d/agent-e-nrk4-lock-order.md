### Fixed

- hub: confirming an account deletion no longer deadlocks with another change of the same
  account at the same moment: a password reset link, the link that lifts the daily
  second-factor cap, an admin's second-factor reset link, an admin's request for that link, or
  the operator's `maity-hub second-factor reset`. Each now takes the account's lock first, as
  the deletion does, so one waits for the other. A password reset that comes first withdraws
  the pending deletion, which then deletes nothing; after the other changes the account is
  deleted; a link pressed after the deletion does nothing (§2.8.3, §2.8.6, §2.9, §2.10).
