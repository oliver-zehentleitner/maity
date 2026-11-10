### Fixed

- hub: the last `go` on a change of a bridge's purpose names a side that left the project as
  `not_a_member` (the bridge) or `not_an_agent` (the served agent), as a new connection's does,
  instead of `isolated` (§2.3).
