### Changed

- hub: accepting an invitation (`POST /invitations/{token}/accept`) needs a session in good
  standing, as docs/api.md §3.4 says: a session signed in by a mail link or code alone gets
  `forbidden` with `details.reason: not_in_good_standing` until it is confirmed, and the
  invitation stays open.
