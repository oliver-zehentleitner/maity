### Fixed

- hub: confirming an account deletion no longer deadlocks with a write that holds a project's
  or an organisation's lock and then writes the account's record: a personal request or a
  chat request filed to the account, a restricted card's notice, a jour fixe filing, or the
  revocation of an organisation's invitation to it. The deletion now locks every project and
  organisation it touches in its first pass, in one order, so one waits for the other. A
  sign-in in a browser that still holds the account's session waits for the deletion too, and
  then signs in (§2.6.5, §2.9, §6.26).
