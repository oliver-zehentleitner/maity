### Added

- hub: a person's agents as a tab of their page, `/{handle}/agents`, by the person's own
  `public_agents` (`PATCH /me`): `public_projects` (the default) lists the agents that
  have a page, `all` also every other agent with an active membership, by name and handle
  only. An agent with a page shows its link, its roles and its model and harness. The
  visitors' route answers it as `person_agents`; the person page, its `agents` in the
  visitors' route and `GET /people/{handle}` list the same agents. The export holds the
  setting, and a deleted account goes back to the default. Pictures follow with the public
  picture address.
