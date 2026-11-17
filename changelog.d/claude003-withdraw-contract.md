### Changed

- docs: the contract's §7 no longer says a personal request is `not_found` for every caller
  of the project withdraw route. It names the four that have a withdrawal rule of their
  own there: a cross-owner `reports_to` request and a change of another owner's agent
  (§6.2), a bridge owner's consent (§2.3) and a consent to a transfer into an organisation
  (§6.26). §6.2 "Another owner's agent" now says that whoever asked for the change
  withdraws it on the project route, and the owner under `/requests/{id}/withdraw`. The
  help of `maity request withdraw` follows. No behaviour changes.
