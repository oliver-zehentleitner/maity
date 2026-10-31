### Added

- hub: a bridge reads for the agents it serves (§2.3): `GET …/events?for=<member id>` and its
  long-poll answer what the served agent reads, acknowledge nothing and mark nothing delivered,
  one wait per served agent beside the bridge's own; with `Maity-For` it reads the served
  agent's direct conversation. A served agent without a session of its own is present through
  its bridges, and a request asked through a bridge wakes the served agent as `member:`.
