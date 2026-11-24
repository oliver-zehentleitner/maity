### Changed

- hub: accepting an invitation needs a session in good standing, as docs/api.md §3.4 says,
  both ways: the accept by token (`POST /invitations/{token}/accept`) and the `go` on the
  inbox request of an invitation by handle (`POST /requests/{id}/answer`). A session signed
  in by a mail link or code alone gets `forbidden` with `details.reason:
  not_in_good_standing` until it is confirmed; the invitation, and its request, stay open.
  A `no` still declines from any session.
