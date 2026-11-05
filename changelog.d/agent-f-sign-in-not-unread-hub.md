### Changed

- hub: a new sign-in is no longer a bell item: `GET /me/notifications` neither lists, counts nor
  pins it, and "This was me" marks nothing read. The answer gains `sessions_rev`, and a held
  long-poll also returns on a session record. The sign-in mail stays.
