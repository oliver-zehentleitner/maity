### Fixed

- cli: a runner keeps the running count it reports to the hub correct across a reconnect.
  After the connection dropped and the runner said `hello` again, `maity runners` could show
  a stale count for the runner — `0/N` while its placements kept running, or an old number
  after they ended — until something else changed. The runner now carries the last counted
  total on every `hello` and re-sends the current count on the next tick after a reconnect,
  whatever the count.
