### Security

- hub: every rate limit keyed by a mail address (the login's count for an address of no
  account, the pair and per-recipient limits of the sign-in link, the password reset and the
  registration, and the per-recipient limits of verification mails) counts the address by one
  keyed fingerprint (HMAC under a key derived from `MAITY_SECRET_KEY`, else the address lock's
  pepper), never by the address or a plain SHA-256 of it, also in `rate_count` on PostgreSQL.
  The keys change, so on deploy these limits start counting again once.
