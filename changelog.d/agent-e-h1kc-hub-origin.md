### Changed

- cli: a clone's hub is fixed once its state names one. `maity resume --hub`
  and `maity help --hub` on such a clone pass only for the stored hub's
  origin (scheme, host and port; case, an explicit default port and the
  spelling of an IP literal do not matter) and leave the stored URL as it is;
  another origin is refused with exit 4 before anything is written or sent,
  naming both origins. The hub changes only by a new join. A first
  `resume --hub` after the page-driven join, with no state yet, works as
  before. `maity help --hub` in a clone whose state directory cannot be
  named (a runner's clone it cannot place, git missing) is refused with
  exit 4 and fetches nothing; outside a Git clone it fetches as before.
- cli: a hub URL with an empty user or password (`https://@hub.example`) is
  refused like one with credentials in it.
