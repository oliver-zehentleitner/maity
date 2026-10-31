### Added

- Contract §2.3: the role `bridge` lends its hands to agents that cannot reach the repository or the CLI (a cloud-only designer): the served agent's membership names its bridge, the bridge acts for it with the signed `Maity-For` header (§2.2), recorded as the served agent with `via` the bridge, without governance scopes; one bridge may serve several agents. `GET …/roles` lists the built-in roles with their description, guide text and scopes, so the dashboard can explain each role.
