### Changed

- hub: placement rejoin follows the owner rule. Every start of a placement whose
  credential was revoked follows the owner rule of the restart (§15.6), whether a
  `rejoin` is stored yet or not, and a clone's `removed` report for a running placement
  whose credential only the agent profile's owner may bring back also sets
  `desired: stopped`, so its rejoin waits for the owner's start (§15.5, §15.8).
