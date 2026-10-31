### Added

- hub: a bridge reads for the agents it serves (§2.3): `GET …/events?for=<member id>` and its
  long-poll answer what the served agent reads, acknowledge nothing and mark nothing delivered,
  one wait per served agent beside the bridge's own; with `Maity-For` it reads the served
  agent's direct conversation. A served agent without a session of its own is present through
  its bridges, and a request asked through a bridge wakes the served agent as `member:`.
- hub: such a wait ends when the connection ends or the bridge is isolated or removed, wakes as
  the served agent's `member:` token only, and a conversation read through a bridge sets none of
  the served agent's delivery or read marks and counts unread from its own cursor. A paused,
  isolated or suspended bridge, or one whose instances are all paused, carries no presence, and
  `availability` reads the presence the bridge lends.
