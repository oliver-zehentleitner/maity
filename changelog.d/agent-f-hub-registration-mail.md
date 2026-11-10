### Added

- hub: the mail of a registration (`docs/api.md` §2.7.1) — the confirmation link
  (`/mail/register/{token}`, valid 24 hours, a signed token whose nonce the hub keeps only as
  a hash) and the note to an address that has an account already, both through the mail
  outbox in the transaction of the request, in the language of its `Accept-Language`, with no
  unsubscribe part. They count against a budget of their own, `registration_max_per_hour`
  (default 30, `MAITY_MAIL_REGISTRATION_MAX_PER_HOUR`); over it a mail is dropped and
  `registration_dropped_last_hour` counts it. The link page itself follows.
