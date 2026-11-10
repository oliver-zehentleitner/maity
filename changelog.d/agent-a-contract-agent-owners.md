### Added

- Contract §6.1, §6.2: `policy.agent_owners` (`members` or `anyone`, by default `anyone` only with a public page). Under `members` the hub isolates an agent as soon as its owner's membership ends, withdraws the open requests to that owner about it and allows the lift only once the owner is back; under both, a leaving member's open joins are revoked and their unredeemed placements closed.
- Contract §6.1, §6.2: `policy.outside_roles` (default `["coder"]`): an agent of an owner from outside never holds trust `admin` or a reviewing, testing, managing, ops or proxy role, and its reviews move no card.
