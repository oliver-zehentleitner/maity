### Changed

- docs/api.md: the position of `GET /me/notifications` (`after`, `next_after`, `up_to`) is an
  opaque token that clients pass back unchanged, holding one position per project the human is
  a member of and one for the account records (§18.2, §18.3, §18.8, §1.4, cap in §1.7). Order
  is guaranteed per project and per account, not globally, so no hub-wide write lock is needed;
  a project joined later starts at its join-time position, one left drops out, and a position
  in the earlier `a.b` form is `invalid`.
