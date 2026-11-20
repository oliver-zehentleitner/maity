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
- cli: under a placement, `--hub` names only the clone's hub: with no stored
  hub, `maity help --hub` and `maity resume --hub` are refused with exit 4
  and nothing is sent.
- cli: a placed session never joins: `maity join` with `MAITY_PLACEMENT`
  (even empty) or `MAITY_GIT_PRIVATE` set is refused with exit 4 before any
  call, since the runner's pickup and exchange join a placement. A runner's
  clone without its placement is refused too, instead of joining into a
  directory of the agent's own; outside a Git clone or without git, an
  unplaced join works as before. A placed clone with a credential but no hub
  is told that the runner joins the placement again.
- cli: a hub URL with an empty user or password (`https://@hub.example`) is
  refused like one with credentials in it.
