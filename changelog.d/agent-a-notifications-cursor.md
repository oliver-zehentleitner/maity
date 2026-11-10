### Changed

- docs/api.md: the position of `GET /me/notifications` (`after`, `next_after`, `up_to`) is an
  opaque token that clients pass back unchanged, holding one position per project the human is
  a member of and one for the account records (§18.2, §18.3, §18.8, §1.4, cap in §1.7). It is
  sealed (AES-256-GCM, a position key derived from `MAITY_SECRET_KEY` or, without it, kept in
  the database) and bound to the human, inline normally and as a handle to a
  stored vector when it would exceed the cap. Order is guaranteed per project and per account,
  not globally, so no hub-wide write lock is needed; a project joined later starts at its
  join-time position, one left drops out. A position that does not open for the human, the
  earlier `a.b` form included, is `invalid` (`"position"`): the long-poll restarts at the head,
  "mark all read" marks nothing and is not retried on its own.
