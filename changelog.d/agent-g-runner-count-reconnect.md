### Fixed

- cli: a runner keeps its reported running count correct across a reconnect to the hub.
  After the connection dropped and the runner said `hello` again, `maity runners` could
  show a runner at `0/N running` while its placements kept running; the runner now sends
  the live count on every `hello` and re-asserts it on the next tick after reconnecting.
