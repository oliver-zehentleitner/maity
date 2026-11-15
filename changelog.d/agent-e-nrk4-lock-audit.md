### Fixed

- hub: confirming an account deletion no longer deadlocks with a sign-in of the same account
  at the same moment (by password, by a mailed link or its code), with the mail of a sign-in
  or password reset link to it, with the hourly pass over the agents that do not listen, or
  with the mail worker or the forge writing the account's record (a third hard failure, a
  refused token, a suspended or removed installation). Each now takes the account's lock first,
  as the deletion does, so one waits for the other; a sign-in that waited for the deletion is
  refused, and nothing is mailed (§2.6, §2.9, §2.10, §5.3, §11.4, §18.7).
