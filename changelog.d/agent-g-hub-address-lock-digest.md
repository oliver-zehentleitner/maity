### Fixed

- hub: the per-address locks (`address_lock`, `registration_lock`) hold an HMAC of the
  normalized address instead of the address, so a deleted account's address no longer
  stays in them (§2.9), nor any address that once started a registration. The key comes
  from `MAITY_SECRET_KEY`, else from a random pepper the hub stores at first use.
  Migration 0085 makes both tables again; their old rows are only locks and go.
