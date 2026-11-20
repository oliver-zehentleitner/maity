### Changed

- cli: a clone's hub is fixed once its state names one. `maity resume --hub`
  and `maity help --hub` on such a clone pass only for the stored hub's
  origin (scheme, host and port; case and an explicit default port do not
  matter) and leave the stored URL as it is; another origin is refused with
  exit 4 before anything is written or sent, naming the stored hub's origin.
  The hub changes only by a new join. A first `resume --hub` after the
  page-driven join, with no state yet, works as before.
