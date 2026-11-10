### Fixed

- hub: the per-address locks (`address_lock`, `registration_lock`) hold an HMAC of the
  normalized address instead of the address, so a deleted account's address no longer
  stays in them (§2.9), nor any address that once started a registration. The key comes
  from `MAITY_SECRET_KEY`, else from a random pepper the hub stores at first use.
  Migration 0085 makes both tables again; their old rows are only locks and go.
- hub: an account deletion also removes the lock rows of the account's addresses (§2.9).
- hub: a verification whose claim the unique constraint catches answers as a dead link,
  not with an error.
