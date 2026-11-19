### Added

- hub: the join page (§3.2 item 2) says "You will read and write this
  project's restricted texts." when the project's restricted-access set
  would hold the membership the exchange creates, resolved when the page is
  served; nothing for a new instance or a replacement, never a count of
  cards. `GET /invitations/{token}` answers `restricted_texts`: `true` under
  `all_except` for an invitation above `guest`, `false` otherwise (§3.4).
